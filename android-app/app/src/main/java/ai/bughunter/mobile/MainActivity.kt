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
    val name: String,
    val platform: String,
    val handle: String,
    val reward: String,
    val url: String,
    val score: Int
)

private data class LedgerLine(val label: String, val value: String)

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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BugHunterScreen() {
    var token by remember { mutableStateOf("") }
    var connected by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Connect to the Termux engine on this device.") }
    var opportunities by remember { mutableStateOf(listOf<Opportunity>()) }
    var ledger by remember { mutableStateOf(listOf<LedgerLine>()) }
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
                val opportunityJson = withContext(Dispatchers.IO) {
                    apiCall("/opportunities?limit=100", token)
                }
                val list = JSONObject(opportunityJson).getJSONArray("opportunities")
                val parsed = mutableListOf<Opportunity>()
                for (i in 0 until list.length()) {
                    val item = list.getJSONObject(i)
                    parsed.add(Opportunity(
                        item.optString("name", item.optString("handle")),
                        item.optString("platform"),
                        item.optString("handle"),
                        item.optString("reward"),
                        item.optString("url"),
                        item.optInt("score")
                    ))
                }
                val ledgerJson = withContext(Dispatchers.IO) { apiCall("/ledger", token) }
                val summary = JSONObject(ledgerJson).getJSONArray("summary")
                val lines = mutableListOf<LedgerLine>()
                for (i in 0 until summary.length()) {
                    val item = summary.getJSONObject(i)
                    lines.add(LedgerLine(
                        item.optString("currency") + " " + item.optString("kind"),
                        item.optString("total")
                    ))
                }
                withContext(Dispatchers.IO) { apiCall("/health", token) }
                opportunities = parsed
                ledger = lines
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
                                value = token,
                                onValueChange = { token = it },
                                label = { Text("Termux API token") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                            Button(onClick = { refresh() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                                Text(if (busy) "Connecting…" else "Connect / Refresh")
                            }
                            Text(
                                if (connected) "Connected" else "Not connected",
                                color = if (connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                            )
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
                item {
                    Text("BOUNTY LEDGER", style = MaterialTheme.typography.titleMedium)
                    if (ledger.isEmpty()) Text("No ledger entries yet. Add them with cbh ledger add in Termux.")
                }
                items(ledger) { line ->
                    Card {
                        Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(line.label)
                            Text(line.value)
                        }
                    }
                }
                item {
                    Text(
                        "Safety: the companion connects only to 127.0.0.1. It does not run scans, exploit targets, or submit reports.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}
