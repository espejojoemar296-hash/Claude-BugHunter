package ai.bughunter.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
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
    val reward: String, val url: String, val score: Int
)
private data class LedgerLine(val label: String, val value: String)
private data class WorkspaceFile(val path: String, val size: Int)
private data class ApprovedTarget(val file: String, val target: String, val scopeFile: String, val scopePreview: String)

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
    var ledger by remember { mutableStateOf(listOf<LedgerLine>()) }
    var findings by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var evidence by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var reports by remember { mutableStateOf(listOf<WorkspaceFile>()) }
    var approvals by remember { mutableStateOf(listOf<ApprovedTarget>()) }
    var scopePreview by remember { mutableStateOf("No scope.md found in the project folder.") }
    var telegramConfigured by remember { mutableStateOf(false) }
    var engagementStatus by remember { mutableStateOf("No engagement has been run.") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

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
                        apiCall("/engagement/status", token)
                    )
                }
                val list = JSONObject(payload[1]).getJSONArray("opportunities")
                val parsed = mutableListOf<Opportunity>()
                for (i in 0 until list.length()) {
                    val item = list.getJSONObject(i)
                    parsed.add(Opportunity(
                        item.optString("name", item.optString("handle")),
                        item.optString("platform"), item.optString("handle"),
                        item.optString("reward"), item.optString("url"), item.optInt("score")
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
    }
}
