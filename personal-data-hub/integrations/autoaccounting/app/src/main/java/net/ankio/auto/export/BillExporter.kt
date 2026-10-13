package net.ankio.auto.export

import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import net.ankio.auto.http.RequestsUtils
import net.ankio.auto.http.api.BillAPI
import net.ankio.auto.utils.PrefManager
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.ezbook.server.constant.BillState
import org.ezbook.server.db.model.BillInfoModel
import org.ezbook.server.tools.runCatchingExceptCancel
import java.time.LocalDate
import java.time.ZoneId
import java.util.concurrent.TimeUnit

data class BillExportResult(val stateCounts: Map<String, Int>, val posted: Int) {
    val pulled: Int get() = stateCounts.values.sum()
}

class BillExportFailure(
    val kind: String,
    val stateCounts: Map<String, Int>,
    val posted: Int,
    cause: Throwable,
) : Exception(kind, cause)

object BillExporter {
    private val zone = ZoneId.of("Asia/Shanghai")
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()
    private val states = listOf(BillState.Synced, BillState.Edited, BillState.Wait2Edit)

    suspend fun exportDay(day: LocalDate): Result<BillExportResult> = withContext(Dispatchers.IO) {
        val counts = linkedMapOf<String, Int>()
        var posted = 0
        runCatchingExceptCancel {
            check(PrefManager.billExportEnabled) { "disabled" }
            val endpoint = PrefManager.billExportUrl.trim().trimEnd('/')
            val token = PrefManager.billExportToken.trim()
            check(endpoint.startsWith("https://")) { "endpoint_must_be_https" }
            check(token.isNotEmpty()) { "token_missing" }

            val start = day.atStartOfDay(zone).toInstant().toEpochMilli()
            val end = day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()

            // Pull all three states before posting anything. An empty successful list is valid;
            // any failed local call aborts the entire run and leaves NAS files untouched.
            val bills = mutableListOf<BillInfoModel>()
            for (state in states) {
                val stateBills = BillAPI.exportList(state, start, end).getOrThrow()
                counts[state.name] = stateBills.size
                bills += stateBills
            }

            if (!BillDeletionOutbox.seeded()) seedKnownBills(endpoint, token)
            val pending = BillDeletionOutbox.discover()
            for (chunk in pending.chunked(1000)) {
                val deleteUrl = endpoint.substringBeforeLast("/bills") + "/deletions"
                val deletion = Request.Builder().url(deleteUrl)
                    .header("Authorization", "Bearer $token")
                    .post(gson.toJson(mapOf("bill_ids" to chunk)).toRequestBody("application/json; charset=utf-8".toMediaType())).build()
                client.newCall(deletion).execute().use { response ->
                    check(response.isSuccessful) { "nas_http_${response.code}" }
                    val ack = gson.fromJson(response.body?.string() ?: error("nas_empty_response"), JsonObject::class.java)
                    check(ack.get("ok")?.asBoolean == true) { "nas_deletion_not_acknowledged" }
                }
                BillDeletionOutbox.acknowledge(chunk)
            }
            for (bill in bills) {
                // 先持久化 ID：NAS 已提交但客户端未收到 ACK 时也能追踪后续删除。
                BillDeletionOutbox.remember(bill.id)
                val request = Request.Builder()
                    .url(endpoint)
                    .header("Authorization", "Bearer $token")
                    .header("Content-Type", "application/json; charset=utf-8")
                    .post(gson.toJson(bill).toRequestBody("application/json; charset=utf-8".toMediaType()))
                    .build()
                client.newCall(request).execute().use { response ->
                    check(response.isSuccessful) { "nas_http_${response.code}" }
                    val ack = gson.fromJson(response.body?.string() ?: error("nas_empty_response"), JsonObject::class.java)
                    check(ack.get("ok")?.asBoolean == true && ack.get("bill_id")?.asLong == bill.id) { "nas_bill_not_acknowledged" }
                }
                posted++
            }
            BillExportResult(counts.toMap(), posted)
        }.recoverCatching { error ->
            throw BillExportFailure(shortError(error), counts.toMap(), posted, error)
        }
    }

    /** 首次升级从 NAS 完整读取已归档 ID，使历史账单也能跟踪删除。 */
    private fun seedKnownBills(endpoint: String, token: String) {
        val ids = mutableSetOf<Long>()
        var offset = 0
        for (page in 0 until 10000) {
            val request = Request.Builder().url("$endpoint/ids?offset=$offset&limit=1000")
                .header("Authorization", "Bearer $token").get().build()
            val doc = client.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "nas_http_${response.code}" }
                gson.fromJson(response.body?.string() ?: error("nas_empty_response"), JsonObject::class.java)
            }
            check(doc.get("ok")?.asBoolean == true) { "nas_inventory_not_acknowledged" }
            for (value in doc.getAsJsonArray("bill_ids")) {
                val id = value.asLong; check(id > 0) { "nas_inventory_invalid_id" }; ids.add(id)
            }
            val next = doc.get("next_offset")
            if (next == null || next.isJsonNull) { BillDeletionOutbox.seed(ids); return }
            check(next.asInt > offset) { "nas_inventory_stalled" }; offset = next.asInt
        }
        error("nas_inventory_incomplete")
    }

    private fun shortError(error: Throwable): String = when {
        error.message in setOf("disabled", "endpoint_must_be_https", "token_missing") -> error.message!!
        error.message?.startsWith("nas_http_") == true -> error.message!!
        error is RequestsUtils.HttpException -> "local_http_${error.code}"
        error is java.io.IOException -> "network_io"
        else -> error.javaClass.simpleName.take(40)
    }
}
