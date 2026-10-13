package net.ankio.auto.export

import android.content.Context
import net.ankio.auto.autoApp
import net.ankio.auto.http.LocalNetwork
import org.ezbook.server.db.model.BillInfoModel

/** 已导出 ID 和待删除事件持久化；仅本地成功读取为 null 才认定删除。 */
object BillDeletionOutbox {
    private val pref get() = autoApp.getSharedPreferences("bill-export-deletions", Context.MODE_PRIVATE)

    @Synchronized
    fun seeded(): Boolean = pref.getBoolean("seeded", false)

    @Synchronized
    fun seed(ids: Set<Long>) {
        val known = pref.getStringSet("known", emptySet())!!.toMutableSet()
        known.addAll(ids.map { it.toString() })
        check(pref.edit().putStringSet("known", known).putBoolean("seeded", true).commit()) { "outbox_persist_failed" }
    }

    @Synchronized
    fun remember(id: Long) {
        val known = pref.getStringSet("known", emptySet())!!.toMutableSet()
        known.add(id.toString())
        check(pref.edit().putStringSet("known", known).commit()) { "outbox_persist_failed" }
    }

    suspend fun discover(): List<Long> {
        val known = synchronized(this) { pref.getStringSet("known", emptySet())!!.toSet() }
        for (id in known) {
            // 网络失败抛异常，不把连接失败误认为源端删除。
            val result = LocalNetwork.get<BillInfoModel>("bill/get?id=$id").getOrThrow()
            check(result.code == 200) { "local_result_${result.code}" }
            if (result.data == null) synchronized(this) {
                val pending = pref.getStringSet("pending", emptySet())!!.toMutableSet()
                pending.add(id)
                check(pref.edit().putStringSet("pending", pending).commit()) { "outbox_persist_failed" }
            }
        }
        return synchronized(this) { pref.getStringSet("pending", emptySet())!!.map { it.toLong() } }
    }

    @Synchronized
    fun acknowledge(ids: List<Long>) {
        val values = ids.map { it.toString() }.toSet()
        val pending = pref.getStringSet("pending", emptySet())!!.toMutableSet()
        val known = pref.getStringSet("known", emptySet())!!.toMutableSet()
        pending.removeAll(values); known.removeAll(values)
        check(pref.edit().putStringSet("pending", pending).putStringSet("known", known).commit()) { "outbox_persist_failed" }
    }
}
