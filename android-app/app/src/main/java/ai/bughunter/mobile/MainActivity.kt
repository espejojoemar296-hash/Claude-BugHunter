package ai.bughunter.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { BugHunterScreen() }
    }
}

private data class Opportunity(
    val name: String, val platform: String, val handle: String,
    val reward: String, val url: String, val score: Int, val details: String
)
private data class LedgerLine(val label: String, val value: String)
private data class WorkspaceFile(val path: String, val size: Int)
private data class ApprovedTarget(val file: String, val target: String, val scopeFile: String, val scopePreview: String)


private fun formatOpportunityDetails(item: JSONObject): String {
    val details = item.optJSONObject("details") ?: return "Published scope details are not available in the local cache. Open the program page and verify scope before testing."
    val sections = listOf(
        "IN SCOPE" to "in_scope",
        "OUT OF SCOPE" to "out_of_scope",
        "NEEDS MANUAL REVIEW" to "needs_review",
        "OTHER ASSETS" to "other_assets"
    )
    val out = StringBuilder()
    out.append("Reward: ").append(item.optString("reward", "Not published")).append("\\n")
    out.append("Availability: ").append(item.optString("availability", "Unverified")).append("\\n")
    out.append("Scope source: ").append(details.optString("scope_source")).append("\\n")
    for ((label, key) in sections) {
        val array = details.optJSONArray(key) ?: continue
        out.append("\\n").append(label).append(" (").append(array.length()).append(")\\n")
        for (i in 0 until minOf(array.length(), 35)) {
            val asset = array.optJSONObject(i) ?: continue
            out.append("• ").append(asset.optString("asset"))
            if (asset.optString("type").isNotBlank()) out.append(" [").append(asset.optString("type")).append("]")
            if (asset.optString("status").isNotBlank()) out.append(" — ").append(asset.optString("status"))
            if (asset.has("bounty_eligible") && !asset.isNull("bounty_eligible")) {
                out.append("; bounty eligible: ").append(asset.optString("bounty_eligible"))
            }
            if (asset.optString("severity").isNotBlank()) out.append("; severity: ").append(asset.optString("severity"))
            if (asset.optString("instruction").isNotBlank()) out.append("\\n  ").append(asset.optString("instruction"))
            if (asset.optString("notes").isNotBlank()) out.append("\\n  Note: ").append(asset.optString("notes"))
            out.append("\\n")
        }
        if (array.length() > 35) out.append("… ").append(array.length() - 35).append(" more entries omitted here\\n")
    }
    val conduct = details.optJSONArray("conduct")
    if (conduct != null && conduct.length() > 0) {
        out.append("\\nPROGRAM RULES / CONDUCT\\n")
        for (i in 0 until minOf(conduct.length(), 20)) out.append("• ").append(conduct.optString(i)).append("\\n")
    }
    out.append("\\nAlways re-check the live program policy. Scope can change; ambiguous assets are not approved for testing.")
    return out.toString()
}

private fun apiCall(path: String, token: String): String {
    val connection = URL("http://127.0.0.1:8765" + path).openConnection() as HttpURLConnection
    connection.requestMethod = "GET"
    connection.connectTimeout = 3500
    connection.readTimeout = 5000
    connection.setRequestProperty("Authorization", "Bearer " + token)
    return try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader().use { it.readText() }
        if (code !in 200..299) throw IllegalStateException("API returned HTTP " + code + ": " + body)
        body
    } finally {
        connection.disconnect()
    }
}

private fun apiPost(path: String, token: String, body: String): String {
    val connection = URL("http://127.0.0.1:8765" + path).openConnection() as HttpURLConnection
    connection.requestMethod = "POST"
    connection.connectTimeout = 3500
    connection.readTimeout = 5000
    connection.doOutput = true
    connection.setRequestProperty("Authorization", "Bearer " + token)
    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
    return try {
        connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream.bufferedReader().use { it.readText() }
        if (code !in 200..299) throw IllegalStateException("API returned HTTP " + code + ": " + response)
        response
    } finally {
        connection.disconnect()
    }
}

private fun workspaceFiles(json: JSONObject, key: String): List<WorkspaceFile> {
    val array = json.getJSONArray(key)
    val result = mutableListOf<WorkspaceFile>()
    for (i in 0 until array.length()) {
        val item = array.getJSONObject(i)
        result.add(WorkspaceFile(item.optString("path"), item.optInt("size")))
    }
    return result
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BugHunterScreen() {
    var token by remember { mutableStateOf("") }
    var connected by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Connect to the Termux engine on this device.") }
    var opportunities by remember { mutableStateOf(listOf<Opportunity>()) }
    var selectedOpportunity by remember { mutableStateOf<Opportunity?>(null) }
    var ledger by remember { mutableStateOf(listOf<LedgerLine>()) }
    var ledgerAmount by remember { mutableStateOf("") }
    var ledgerCurrency by remember { mutableStateOf("USD") }
    var ledgerNote by remember { mutableStateOf("") }
    var ledgerProgram by remember { mutableStateOf("") }
    var discoveryStatus by remember { mutableStateOf("No discovery run yet.") }
    var findings by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var evidence by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var reports by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var approvals by remember { mutableStateOf(listOf<ApprovedTarget>()) }
    var scopePreview by remember { mutableStateOf("No scope.md found in the project folder.") }
    var telegramConfigured by remember { mutableStateOf(false) }
    var engagementStatus by remember { mutableStateOf("No engagement has been run.") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(connected, token) {
        if (connected && token.isNotBlank()) {
            while (true) {
                delay(30000)
                try {
                    val payload = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/opportunities?limit=100", token))
                    }
                    val list = payload.getJSONArray("opportunities")
                    val parsed = mutableListOf<Opportunity>()
                    for (i in 0 until list.length()) {
                        val item = list.getJSONObject(i)
                        parsed.add(Opportunity(
                            item.optString("name", item.optString("handle")),
                            item.optString("platform"), item.optString("handle"),
                            item.optString("reward"), item.optString("url"), item.optInt("score"),
                            formatOpportunityDetails(item)
                        ))
                    }
                    opportunities = parsed
                    val job = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/opportunities/status", token))
                    }
                    discoveryStatus = when (job.optString("status")) {
                        "running" -> "Discovery running…"
                        "completed" -> "Checked " + job.optInt("checked") + " programs; " + job.optInt("added") + " new."
                        "failed" -> "Discovery failed: " + job.optString("error")
                        else -> discoveryStatus
                    }
                } catch (_: Exception) {
                    // Keep the last successful snapshot visible during a temporary API interruption.
                }
            }
        }
    }

    fun refresh() {
        if (token.isBlank()) {
            status = "Paste the API token printed by python -m cbh.api in Termux."
            return
        }
        busy = true
        scope.launch {
            try {
                val payload = withContext(Dispatchers.IO) {
                    listOf(
                        apiCall("/health", token),
                        apiCall("/opportunities?limit=100", token),
                        apiCall("/ledger", token),
                        apiCall("/workspace", token),
                        apiCall("/engagement/status", token),
                        apiCall("/opportunities/status", token)
                    )
                }
                val list = JSONObject(payload[1]).getJSONArray("opportunities")
                val parsed = mutableListOf<Opportunity>()
                for (i in 0 until list.length()) {
                    val item = list.getJSONObject(i)
                    parsed.add(Opportunity(
                        item.optString("name", item.optString("handle")),
                        item.optString("platform"), item.optString("handle"),
                        item.optString("reward"), item.optString("url"), item.optInt("score"),
                        formatOpportunityDetails(item)
                    ))
                }
                val ledgerJson = JSONObject(payload[2])
                val summary = ledgerJson.getJSONArray("summary")
                val lines = mutableListOf<LedgerLine>()
                for (i in 0 until summary.length()) {
                    val item = summary.getJSONObject(i)
                    lines.add(LedgerLine(
                        item.optString("currency") + " " + item.optString("kind"),
                        item.optString("total")
                    ))
                }
                val workspace = JSONObject(payload[3])
                val scope = workspace.getJSONObject("scope")
                scopePreview = if (scope.optBoolean("exists")) {
                    scope.optString("preview")
                } else {
                    "No scope.md found. Import a program scope in Termux before recon."
                }
                val targetArray = workspace.getJSONArray("approved_targets")
                val targetList = mutableListOf<ApprovedTarget>()
                for (i in 0 until targetArray.length()) {
                    val item = targetArray.getJSONObject(i)
                    targetList.add(ApprovedTarget(
                        item.optString("file"), item.optString("target"), item.optString("scope_file"),
                        item.optString("scope_preview")
                    ))
                }
                val discovery = JSONObject(payload[5])
                discoveryStatus = when (discovery.optString("status")) {
                    "running" -> "Discovery is running…"
                    "completed" -> "Checked " + discovery.optInt("checked") +
                        " programs; " + discovery.optInt("added") + " new."
                    "failed" -> "Discovery failed: " + discovery.optString("error")
                    else -> "No discovery run yet."
                }
                opportunities = parsed
                ledger = lines
                findings = workspaceFiles(workspace, "findings")
                evidence = workspaceFiles(workspace, "evidence")
                reports = workspaceFiles(workspace, "reports")
                approvals = targetList
                telegramConfigured = workspace.optBoolean("telegram_configured")
                val job = JSONObject(payload[4])
                engagementStatus = when (job.optString("status")) {
                    "running" -> "Running: " + job.optString("config")
                    "completed" -> {
                        val completed = job.optJSONObject("result")
                        "Completed: " + job.optString("config") + " · Report: " +
                            (completed?.optString("report") ?: "not generated")
                    }
                    "failed" -> "Failed: " + job.optString("error")
                    else -> "Idle"
                }
                connected = true
                status = "Connected to the local Termux engine."
            } catch (error: Exception) {
                connected = false
                status = error.message ?: "Could not connect. Check that the Termux API is running."
            } finally {
                busy = false
            }
        }
    }

    fun startDiscovery() {
        if (token.isBlank()) {
            status = "Connect to the Termux engine first."
            return
        }
        busy = true
        scope.launch {
            var completed = false
            try {
                withContext(Dispatchers.IO) { apiPost("/opportunities/refresh", token, "{}") }
                discoveryStatus = "Discovery running…"
                for (attempt in 0 until 90) {
                    delay(1000)
                    val job = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/opportunities/status", token))
                    }
                    val state = job.optString("status")
                    discoveryStatus = when (state) {
                        "running" -> "Discovery running…"
                        "completed" -> "Checked " + job.optInt("checked") + " programs; " +
                            job.optInt("added") + " new programs saved."
                        "failed" -> "Discovery failed: " + job.optString("error")
                        else -> "Waiting for discovery…"
                    }
                    if (state == "completed") {
                        completed = true
                        break
                    }
                    if (state == "failed") break
                }
                status = if (completed) "Discovery complete. Program details refreshed." else discoveryStatus
            } catch (error: Exception) {
                status = error.message ?: "Could not complete bounty discovery."
            } finally {
                busy = false
            }
            if (completed) refresh()
        }
    }

    fun recordTransaction(kind: String) {
        val amount = ledgerAmount.toDoubleOrNull()
        if (amount == null || amount <= 0.0 || !amount.isFinite()) {
            status = "Enter a valid positive amount."
            return
        }
        busy = true
        scope.launch {
            var shouldRefresh = false
            try {
                val body = JSONObject()
                    .put("kind", kind)
                    .put("amount", amount)
                    .put("currency", ledgerCurrency.trim().ifBlank { "USD" })
                    .put("note", ledgerNote)
                    .put("program", ledgerProgram)
                    .toString()
                withContext(Dispatchers.IO) { apiPost("/ledger", token, body) }
                ledgerAmount = ""
                ledgerNote = ""
                status = if (kind == "income") "Bounty income recorded." else "Expense recorded."
                shouldRefresh = true
            } catch (error: Exception) {
                status = error.message ?: "Could not save ledger entry."
            } finally {
                busy = false
            }
            if (shouldRefresh) refresh()
        }
    }

    fun startEngagement(configFile: String) {
        if (token.isBlank()) {
            status = "Connect to the Termux engine first."
            return
        }
        busy = true
        scope.launch {
            try {
                val body = JSONObject().put("config", configFile).toString()
                val response = withContext(Dispatchers.IO) {
                    apiPost("/engagement/run", token, body)
                }
                engagementStatus = "Started: " + configFile
                status = response
            } catch (error: Exception) {
                status = error.message ?: "Could not start engagement."
            } finally {
                busy = false
            }
        }
    }

    MaterialTheme {
        Scaffold(
            topBar = { TopAppBar(title = { Text("BugHunter AI") }) }
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Card {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("LOCAL ENGINE", style = MaterialTheme.typography.labelLarge)
                            Text(status, style = MaterialTheme.typography.bodyMedium)
                            OutlinedTextField(
                                value = token, onValueChange = { token = it },
                                label = { Text("Termux API token") },
                                modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            Button(onClick = { refresh() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                                Text(if (busy) "Connecting…" else "Connect / Refresh")
                            }
                            Text(if (connected) "Connected" else "Not connected",
                                color = if (connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                        }
                    }
                }
                item {
                    Text("BOUNTY OPPORTUNITIES", style = MaterialTheme.typography.titleMedium)
                    Text(opportunities.size.toString() + " saved opportunities")
                    Text(discoveryStatus, style = MaterialTheme.typography.bodySmall)
                    Button(
                        onClick = { startDiscovery() },
                        enabled = connected && !busy,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Discover / refresh bounty programs") }
                }
                if (opportunities.isEmpty()) {
                    item { Text("No saved opportunities yet. Run cbh hunt or cbh autopilot --once in Termux.") }
                } else {
                    items(opportunities) { item ->
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(item.name, style = MaterialTheme.typography.titleSmall)
                                Text(item.platform + " · " + item.handle)
                                Text("Score: " + item.score + if (item.reward.isNotBlank()) " · " + item.reward else "")
                                if (item.url.isNotBlank()) Text(item.url, style = MaterialTheme.typography.bodySmall)
                                TextButton(onClick = { selectedOpportunity = item }) { Text("View full program details and scope") }
                            }
                        }
                    }
                }
                item {
                    Card {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("BOUNTY INCOME & EXPENSES", style = MaterialTheme.typography.titleMedium)
                            if (ledger.isEmpty()) {
                                Text("No ledger entries recorded yet.", style = MaterialTheme.typography.bodySmall)
                            } else {
                                ledger.forEach { line ->
                                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                        Text(line.label)
                                        Text(line.value, style = MaterialTheme.typography.bodyMedium)
                                    }
                                }
                            }
                            OutlinedTextField(
                                value = ledgerAmount, onValueChange = { ledgerAmount = it },
                                label = { Text("Amount") }, modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            OutlinedTextField(
                                value = ledgerCurrency, onValueChange = { ledgerCurrency = it },
                                label = { Text("Currency (e.g. USD, PHP)") }, modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            OutlinedTextField(
                                value = ledgerProgram, onValueChange = { ledgerProgram = it },
                                label = { Text("Program (optional)") }, modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            OutlinedTextField(
                                value = ledgerNote, onValueChange = { ledgerNote = it },
                                label = { Text("Note (optional)") }, modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { recordTransaction("income") },
                                    enabled = connected && !busy,
                                    modifier = Modifier.weight(1f)
                                ) { Text("Record income") }
                                OutlinedButton(
                                    onClick = { recordTransaction("expense") },
                                    enabled = connected && !busy,
                                    modifier = Modifier.weight(1f)
                                ) { Text("Record expense") }
                            }
                        }
                    }
                }

                item { Text("FINDINGS", style = MaterialTheme.typography.titleMedium) }
                if (findings.isEmpty()) item { Text("No findings files in findings/.") }
                else items(findings) { Text(it.path + " · " + it.size + " bytes") }

                item { Text("EVIDENCE", style = MaterialTheme.typography.titleMedium) }
                if (evidence.isEmpty()) item { Text("No evidence files in evidence/.") }
                else items(evidence) { Text(it.path + " · " + it.size + " bytes") }

                item { Text("REPORT DRAFTS", style = MaterialTheme.typography.titleMedium) }
                if (reports.isEmpty()) item { Text("No files in reports/ or drafts/.") }
                else items(reports) { Text(it.path + " · " + it.size + " bytes") }

                item {
                    Card {
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("SCOPE", style = MaterialTheme.typography.titleMedium)
                            Text(scopePreview, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                item {
                    Card {
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("ENGAGEMENT STATUS", style = MaterialTheme.typography.titleMedium)
                            Text(engagementStatus, style = MaterialTheme.typography.bodySmall)
                            Text("Runs scope-checked recon, endpoint discovery, risk ranking and a report without a paid AI subscription. Findings are leads, not confirmed vulnerabilities. No automatic report submission.",
                                style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                item {
                    Text("APPROVED TARGETS", style = MaterialTheme.typography.titleMedium)
                    if (approvals.isEmpty()) Text("No approval files in targets/approved/.")
                }
                items(approvals) { item ->
                    Card {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(item.target, style = MaterialTheme.typography.titleSmall)
                            Text(item.scopeFile + " · " + item.file, style = MaterialTheme.typography.bodySmall)
                            if (item.scopePreview.isNotBlank()) {
                                Text(item.scopePreview, style = MaterialTheme.typography.bodySmall)
                            } else {
                                Text("Scope preview unavailable — inspect the scope file before starting.",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                            }
                            Button(
                                onClick = { startEngagement(item.file) },
                                enabled = connected && !busy,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text("Start scope recon") }
                        }
                    }
                }
                item {
                    Card {
                        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("TELEGRAM ALERTS")
                            Text(if (telegramConfigured) "Configured" else "Not configured")
                        }
                    }
                }
                item {
                    Text(
                        "Safety: the companion connects only to 127.0.0.1. It does not run scans, exploit targets, or submit reports. Configure Telegram with cbh telegram-setup in Termux.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
        selectedOpportunity?.let { selected ->
            AlertDialog(
                onDismissRequest = { selectedOpportunity = null },
                title = { Text(selected.name) },
                text = {
                    Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState())) {
                        Text(selected.platform + " · " + selected.handle)
                        if (selected.url.isNotBlank()) Text(selected.url)
                        Spacer(Modifier.height(8.dp))
                        Text(selected.details, style = MaterialTheme.typography.bodySmall)
                    }
                },
                confirmButton = {
                    TextButton(onClick = { selectedOpportunity = null }) { Text("Close") }
                }
            )
        }
    }
}
