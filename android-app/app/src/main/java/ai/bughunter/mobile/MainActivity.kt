package ai.bughunter.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
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
private data class AuditFinding(
    val file: String, val line: Int, val category: String, val risk: Int,
    val priority: String, val confidence: String, val function: String, val trace: String
)
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
    out.append("Reward: ").append(item.optString("reward", "Not published")).append("\n")
    out.append("Availability: ").append(item.optString("availability", "Unverified")).append("\n")
    out.append("Scope source: ").append(details.optString("scope_source")).append("\n")
    val cache = details.optJSONObject("scope_cache")
    if (cache != null) {
        val cacheStatus = cache.optString("status", "unknown")
        val ageSeconds = cache.optLong("age_seconds", -1L)
        val ageLabel = if (ageSeconds < 0L) "unknown age" else if (ageSeconds < 3600L) {
            (ageSeconds / 60L).toString() + " minutes old"
        } else {
            (ageSeconds / 3600L).toString() + " hours old"
        }
        out.append("Scope cache: ").append(cacheStatus).append(" · ").append(ageLabel).append("\n")
        if (cache.optString("warning").isNotBlank()) {
            out.append("Cache warning: ").append(cache.optString("warning")).append("\n")
        }
    }
    for ((label, key) in sections) {
        val array = details.optJSONArray(key) ?: continue
        out.append("\n").append(label).append(" (").append(array.length()).append(")\n")
        for (i in 0 until minOf(array.length(), 35)) {
            val asset = array.optJSONObject(i) ?: continue
            out.append("• ").append(asset.optString("asset"))
            if (asset.optString("type").isNotBlank()) out.append(" [").append(asset.optString("type")).append("]")
            if (asset.optString("status").isNotBlank()) out.append(" — ").append(asset.optString("status"))
            if (asset.has("bounty_eligible") && !asset.isNull("bounty_eligible")) {
                out.append("; bounty eligible: ").append(asset.optString("bounty_eligible"))
            }
            if (asset.optString("severity").isNotBlank()) out.append("; severity: ").append(asset.optString("severity"))
            if (asset.optString("instruction").isNotBlank()) out.append("\n  ").append(asset.optString("instruction"))
            if (asset.optString("notes").isNotBlank()) out.append("\n  Note: ").append(asset.optString("notes"))
            out.append("\n")
        }
        if (array.length() > 35) out.append("… ").append(array.length() - 35).append(" more entries omitted here\n")
    }
    val conduct = details.optJSONArray("conduct")
    if (conduct != null && conduct.length() > 0) {
        out.append("\nPROGRAM RULES / CONDUCT\n")
        for (i in 0 until minOf(conduct.length(), 20)) out.append("• ").append(conduct.optString(i)).append("\n")
    }
    out.append("\nAlways re-check the live program policy. Scope can change; ambiguous assets are not approved for testing.")
    return out.toString()
}

private fun discoveryJobSummary(job: JSONObject): String {
    val summary = "Checked " + job.optInt("checked") + " programs; " +
        job.optInt("added") + " new programs saved."
    val warnings = job.optJSONArray("warnings")
    if (warnings == null || warnings.length() == 0) return summary
    val warningText = (0 until minOf(warnings.length(), 3)).joinToString(" · ") {
        warnings.optString(it)
    }
    return summary + " Warning: " + warningText
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
    var selectedProgramName by remember { mutableStateOf("") }
    var ledger by remember { mutableStateOf(listOf<LedgerLine>()) }
    var ledgerAmount by remember { mutableStateOf("") }
    var ledgerCurrency by remember { mutableStateOf("USD") }
    var ledgerNote by remember { mutableStateOf("") }
    var ledgerProgram by remember { mutableStateOf("") }
    var targetInput by remember { mutableStateOf("") }
    var scopeFileInput by remember { mutableStateOf("") }
    var discoveryStatus by remember { mutableStateOf("No discovery run yet.") }
    var findings by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var evidence by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var reports by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var approvals by remember { mutableStateOf(listOf<ApprovedTarget>()) }
    var scopePreview by remember { mutableStateOf("No scope.md found in the project folder.") }
    var telegramConfigured by remember { mutableStateOf(false) }
    var engagementStatus by remember { mutableStateOf("No engagement has been run.") }
    var assessmentStatus by remember { mutableStateOf("No local assessment has been run.") }
    var assessmentRunning by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var activeSection by remember { mutableStateOf("Dashboard") }
    var auditSummary by remember { mutableStateOf("No source audit report found.") }
    var verificationSummary by remember { mutableStateOf("No verification workspaces found.") }
    var auditCandidates by remember { mutableStateOf(listOf<AuditFinding>()) }
    val sections = listOf("Dashboard", "Programs", "Workspace", "Findings", "Verification", "Finance")
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
                        "completed" -> discoveryJobSummary(job)
                        "failed" -> "Discovery failed: " + job.optString("error")
                        else -> discoveryStatus
                    }
                    val engagement = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/engagement/status", token))
                    }
                    val assessment = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/assessment/status", token))
                    }
                    assessmentRunning = assessment.optString("status") in listOf("queued", "running")
                    assessmentStatus = when (assessment.optString("status")) {
                        "queued" -> "Assessment queued…"
                        "running" -> "Running phase: " + assessment.optString("phase")
                        "completed" -> "Completed. Report draft: " + assessment.optString("report")
                        "stopped" -> "Stopped: " + assessment.optString("stop_reason")
                        "failed" -> "Failed: " + assessment.optString("error")
                        else -> assessmentStatus
                    }
                    engagementStatus = when (engagement.optString("status")) {
                        "running" -> "Running: " + engagement.optString("config")
                        "completed" -> {
                            val result = engagement.optJSONObject("result")
                            "Completed: " + engagement.optString("config") + " · Report: " +
                                (result?.optString("report") ?: "not generated")
                        }
                        "failed" -> "Failed: " + engagement.optString("error")
                        else -> "Idle"
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
                    "completed" -> discoveryJobSummary(discovery)
                    "failed" -> "Discovery failed: " + discovery.optString("error")
                    else -> "No discovery run yet."
                }
                opportunities = parsed
                ledger = lines
                findings = workspaceFiles(workspace, "findings")
                evidence = workspaceFiles(workspace, "evidence")
                reports = workspaceFiles(workspace, "reports")
                val audit = workspace.optJSONObject("audit_summary")
                auditSummary = if (audit != null && audit.optBoolean("available")) {
                    "Scanner: " + audit.optString("scanner") +
                        " · Version: " + audit.optString("version") +
                        "\\nCreated: " + audit.optString("created_at") +
                        "\\nFiles scanned: " + audit.optInt("files_scanned") +
                        "\\nCandidate findings: " + audit.optInt("finding_count") +
                        "\\nCandidates are not confirmed vulnerabilities."
                } else {
                    "No readable source-scan-v4.0-report.json found beside the repository."
                }
                val candidateArray = workspace.optJSONArray("audit_candidates")
                val candidateList = mutableListOf<AuditFinding>()
                if (candidateArray != null) {
                    for (i in 0 until candidateArray.length()) {
                        val item = candidateArray.optJSONObject(i) ?: continue
                        candidateList.add(AuditFinding(
                            item.optString("file"), item.optInt("line"), item.optString("category"),
                            item.optInt("risk_score"), item.optString("priority"), item.optString("confidence"),
                            item.optString("function"), item.optString("trace")
                        ))
                    }
                }
                auditCandidates = candidateList
                val counts = workspace.optJSONObject("verification_status_counts")
                verificationSummary = if (counts != null) {
                    var total = 0
                    val states = mutableListOf<String>()
                    val keys = counts.keys()
                    while (keys.hasNext()) {
                        val key = keys.next()
                        val count = counts.optInt(key)
                        total += count
                        states.add(key + ": " + count)
                    }
                    "Total workspaces: " + total +
                        if (states.isEmpty()) "" else "\\n" + states.joinToString(" · ")
                } else {
                    "Verification summary unavailable."
                }

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
                        "completed" -> discoveryJobSummary(job)
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

    fun approveTarget() {
        if (token.isBlank()) {
            status = "Connect to the Termux engine first."
            return
        }
        if (targetInput.isBlank() || scopeFileInput.isBlank()) {
            status = "Enter a target and the path to its reviewed scope Markdown file."
            return
        }
        busy = true
        scope.launch {
            var shouldRefresh = false
            try {
                val body = JSONObject()
                    .put("target", targetInput.trim())
                    .put("scope_file", scopeFileInput.trim())
                    .toString()
                val response = withContext(Dispatchers.IO) {
                    apiPost("/targets/approve", token, body)
                }
                val result = JSONObject(response)
                status = "Scope validated. Approved target saved: " + result.optString("file")
                targetInput = ""
                scopeFileInput = ""
                shouldRefresh = true
            } catch (error: Exception) {
                status = error.message ?: "Could not approve target."
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

    fun startAssessment() {
        if (token.isBlank()) {
            status = "Connect to the Termux engine first."
            return
        }
        busy = true
        scope.launch {
            try {
                val body = JSONObject()
                    .put("mode", "local_only")
                    .put("program", selectedProgramName)
                    .toString()
                withContext(Dispatchers.IO) { apiPost("/assessment/start", token, body) }
                assessmentRunning = true
                assessmentStatus = "Local assessment started…"
                status = "One-tap local assessment started. Live-target testing remains blocked."
                for (attempt in 0 until 300) {
                    delay(1000)
                    val job = withContext(Dispatchers.IO) {
                        JSONObject(apiCall("/assessment/status", token))
                    }
                    val state = job.optString("status")
                    assessmentRunning = state in listOf("queued", "running")
                    assessmentStatus = when (state) {
                        "queued" -> "Assessment queued…"
                        "running" -> "Running phase: " + job.optString("phase")
                        "completed" -> "Completed. Report draft: " + job.optString("report")
                        "stopped" -> "Stopped: " + job.optString("stop_reason")
                        "failed" -> "Failed: " + job.optString("error")
                        else -> assessmentStatus
                    }
                    if (!assessmentRunning) break
                }
            } catch (error: Exception) {
                assessmentStatus = error.message ?: "Could not start local assessment."
            } finally {
                busy = false
            }
        }
    }

    fun stopAssessment() {
        if (token.isBlank()) return
        scope.launch {
            try {
                withContext(Dispatchers.IO) { apiPost("/assessment/stop", token, "{}") }
                assessmentStatus = "Emergency stop requested…"
            } catch (error: Exception) {
                assessmentStatus = error.message ?: "Could not request emergency stop."
            }
        }
    }

    MaterialTheme {
        Scaffold(
            topBar = { TopAppBar(title = { Text("BugHunter AI · " + activeSection) }) },
            bottomBar = {
                NavigationBar {
                    sections.forEach { section ->
                        NavigationBarItem(
                            selected = activeSection == section,
                            onClick = { activeSection = section },
                            icon = { Text(section.take(1)) },
                            label = { Text(section) }
                        )
                    }
                }
            }
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                if (activeSection == "Dashboard") {
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
                    Card {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("ONE-TAP LOCAL ASSESSMENT", style = MaterialTheme.typography.titleMedium)
                            Text(if (selectedProgramName.isBlank()) "No bounty program selected. This run scans local files only." else "Selected program: " + selectedProgramName + " · Policy: NOT VERIFIED", style = MaterialTheme.typography.bodySmall)
                            Text(assessmentStatus, style = MaterialTheme.typography.bodySmall)
                            Text("Scans local source and supported documents, runs static checks and offline synthetic impact simulation, saves evidence and a report draft. No target network requests, no live exploit tests, and no automatic submission.",
                                style = MaterialTheme.typography.bodySmall)
                            Button(
                                onClick = { startAssessment() },
                                enabled = connected && !busy && !assessmentRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text("Start Full Local Assessment") }
                            OutlinedButton(
                                onClick = { stopAssessment() },
                                enabled = connected && assessmentRunning,
                                modifier = Modifier.fillMaxWidth()
                            ) { Text("Emergency Stop") }
                        }
                    }
                }
                item {
                    Card {
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("WORKSPACE OVERVIEW", style = MaterialTheme.typography.titleMedium)
                            Text("Saved programs: " + opportunities.size)
                            Text("Audit candidates: " + auditCandidates.size + " loaded")
                            Text("Evidence files: " + evidence.size + " · Report drafts: " + reports.size)
                            Text(if (connected) "Engine connected" else "Engine disconnected")
                        }
                    }
                }
                }
                if (activeSection == "Programs") {
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
                }
                if (activeSection == "Finance") {
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

                }
                if (activeSection == "Findings") {
                item {
                    Text("STATIC AUDIT CANDIDATES", style = MaterialTheme.typography.titleMedium)
                    Text("Showing up to 100 candidates from the existing source audit. These are unconfirmed leads.",
                        style = MaterialTheme.typography.bodySmall)
                }
                if (auditCandidates.isEmpty()) {
                    item { Text("No audit candidates loaded. Connect to Termux and refresh.") }
                } else {
                    items(auditCandidates) { finding ->
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                                Text(finding.category.ifBlank { "Unclassified candidate" }, style = MaterialTheme.typography.titleSmall)
                                Text(finding.file + ":" + finding.line)
                                Text("Risk score: " + finding.risk + " · " + finding.priority + " · Confidence: " + finding.confidence,
                                    style = MaterialTheme.typography.bodySmall)
                                if (finding.function.isNotBlank()) Text("Function: " + finding.function, style = MaterialTheme.typography.bodySmall)
                                if (finding.trace.isNotBlank()) Text(finding.trace, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                item { Text("WORKSPACE FILES", style = MaterialTheme.typography.titleMedium) }
                if (findings.isEmpty()) item { Text("No additional files in findings/.") }
                else items(findings) { Text(it.path + " · " + it.size + " bytes") }

                item { Text("EVIDENCE", style = MaterialTheme.typography.titleMedium) }
                if (evidence.isEmpty()) item { Text("No evidence files in evidence/.") }
                else items(evidence) { Text(it.path + " · " + it.size + " bytes") }

                item { Text("REPORT DRAFTS", style = MaterialTheme.typography.titleMedium) }
                if (reports.isEmpty()) item { Text("No files in reports/ or drafts/.") }
                else items(reports) { Text(it.path + " · " + it.size + " bytes") }

                }
                if (activeSection == "Workspace") {
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
                        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("ADD SCOPE-APPROVED TARGET", style = MaterialTheme.typography.titleMedium)
                            OutlinedTextField(
                                value = targetInput, onValueChange = { targetInput = it },
                                label = { Text("Target host or URL") },
                                modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            OutlinedTextField(
                                value = scopeFileInput, onValueChange = { scopeFileInput = it },
                                label = { Text("Reviewed scope file (e.g. scopes/program.md)") },
                                modifier = Modifier.fillMaxWidth(), singleLine = true
                            )
                            Text("The local scope engine must accept the target before an approval file is created. This does not start recon.",
                                style = MaterialTheme.typography.bodySmall)
                            Button(
                                onClick = { approveTarget() },
                                enabled = connected && !busy && targetInput.isNotBlank() && scopeFileInput.isNotBlank(),
                                modifier = Modifier.fillMaxWidth()
                            ) { Text("Validate scope & approve target") }
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
                                enabled = connected && !busy && item.scopePreview.isNotBlank(),
                                modifier = Modifier.fillMaxWidth()
                            ) { Text("Start scope recon") }
                        }
                    }
                }
                }
                if (activeSection == "Dashboard") {
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
                }
                if (activeSection == "Dashboard") {
                item {
                    Card {
                        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("TELEGRAM ALERTS")
                            Text(if (telegramConfigured) "Configured" else "Not configured")
                        }
                    }
                }
                }
                if (activeSection == "Verification") {
                    item {
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("SOURCE AUDIT", style = MaterialTheme.typography.titleMedium)
                                Text(auditSummary, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    item {
                        Card {
                            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("VERIFICATION STATUS", style = MaterialTheme.typography.titleMedium)
                                Text(verificationSummary, style = MaterialTheme.typography.bodySmall)
                                Text("NOT_TESTED means no verification has been performed. Static-analysis candidates are leads, not confirmed vulnerabilities.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error)
                            }
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
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { selectedOpportunity = null }) { Text("Close") }
                        TextButton(onClick = {
                            selectedProgramName = selected.name + " (" + selected.platform + ")"
                            selectedOpportunity = null
                            status = "Program selected for local assessment. Verify its live policy manually; network testing remains blocked."
                        }) { Text("Select Program") }
                    }
                }
            )
        }
    }
}
