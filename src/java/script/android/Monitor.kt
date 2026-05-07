package script.android

import java.io.IOException
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

/**
 * 通过 USB 调试（adb）周期性采集与发热相关的手机状态。
 *
 * 参数（顺序随意，可混写）：
 * - 一个数字：采样间隔毫秒，默认 3000，范围 500～60000。
 * - `full` 或 `verbose`：除「一眼看懂」的快照外，还打印各 adb 原始摘要区块。
 *
 * 依赖：本机已安装 adb，手机已开启 USB 调试并授权此电脑。
 */
fun main(args: Array<String>) {
    val intervalMs = args.mapNotNull { it.toLongOrNull() }.firstOrNull()?.coerceIn(500L, 60_000L) ?: 3_000L
    val fullLog = args.any { a -> a.equals("full", true) || a.equals("verbose", true) }
    val adb = AdbSession.resolve()
    println("已连接设备: ${adb.serialOrNull ?: "默认"}，采样间隔: ${intervalMs}ms，模式: ${if (fullLog) "完整" else "快照(推荐)"}。Ctrl+C 结束。")
    println(readingHint())
    adb.assertShellOk("echo ok")

    while (true) {
        println()
        val batteryRaw = adb.shellText("dumpsys battery")
        val thermalRaw = adb.shellText("dumpsys thermalservice")
        val load = adb.shellText("cat /proc/loadavg").trim()
        val cpuPct = adb.cpuUsagePercent()
        val fg = adb.foregroundComponent().lineSequence().firstOrNull()?.trim() ?: ""
        val memAvailKb = parseMemAvailableKb(adb.shellText("cat /proc/meminfo"))
        val brightness = adb.shellText("settings get system screen_brightness").trim()

        println(glanceSnapshot(timestamp(), parseBatterySnapshot(batteryRaw), parseThermalSnapshot(thermalRaw), load, cpuPct, memAvailKb, brightness, fg))
        println("-- 进程 CPU（dumpsys cpuinfo，按占比从高到低） --")
        println(adb.dumpCpuInfoSummary().trimEnd())

        if (fullLog) {
            println()
            println("======== 以下为原始摘要（full 模式） ========")
            printSection("电池") { adb.formatBatterySummary(batteryRaw) }
            printSection("热管理 (thermalservice)") { adb.formatThermalHead(thermalRaw) }
            printSection("温控节点 (部分)") { adb.thermalZoneSnapshot() }
            printSection("负载 & CPU 频率") {
                buildString {
                    appendLine(load.ifEmpty { "(无)" })
                    appendLine(adb.cpuCurFreqSummary())
                }
            }
            printSection("CPU 占用 (估算)") {
                if (cpuPct < 0) "N/A（无法解析 /proc/stat）" else "$cpuPct%"
            }
            printSection("内存概要") { adb.memInfoSummary() }
            printSection("屏幕亮度 (0–255)") { brightness.ifEmpty { "(读失败)" } }
            printSection("前台 (原始行)") { fg.ifEmpty { "(无)" } }
        }
        Thread.sleep(intervalMs)
    }
}

private fun readingHint(): String = """
    ┌─ 日志怎么读（结合你这份样例）────────────────────────────────────
    │ 系统热等级 Thermal Status：0 正常 → 1 轻度 → 2 中等 → 3 严重 …（越高越烫/越可能限频）
    │ SKIN：接近你摸到的「外壳/中框」温度；AP：SoC 一带传感器，通常比皮肤高不少。
    │ BAT：电芯温度；USB：充电路径/接口附近（边充边玩时值得关注）。
    │ 电池 temperature：电池服务上报，多与 BAT 接近；充电时常比待机高。
    │ 若只看结论：每轮优先看「本轮快照」块；需要对照系统原文再开 full。
    └────────────────────────────────────────────────────────────────
""".trimIndent()

private fun glanceSnapshot(
    time: String,
    bat: ParsedBattery,
    th: ParsedThermal,
    loadavg: String,
    cpuPct: Int,
    memAvailKb: Long?,
    brightness: String,
    fg: String,
): String {
    val load1 = loadavg.split(Regex("\\s+")).getOrNull(0) ?: loadavg
    val memStr = memAvailKb?.let { kb -> "%.1f GB".format(Locale.US, kb / 1024.0 / 1024.0) } ?: "N/A"
    val cpuStr = if (cpuPct < 0) "N/A" else "$cpuPct%"
    val chargeHint = when {
        bat.plugged == 0 -> "未接电"
        bat.plugged == 1 -> "AC 充电"
        bat.plugged == 2 -> "USB 充电"
        bat.plugged == 4 -> "无线充电"
        bat.plugged != null -> "供电方式码=${bat.plugged}"
        bat.status == 2 -> "充电中(dumpsys 未带 plugged，口类型未知)"
        else -> "供电:未知"
    }
    val batTemp = bat.tempC?.let { "%.1f °C".format(Locale.US, it) } ?: "N/A"
    val lvl = bat.level?.let { "$it%" } ?: "N/A"
    val st = when (bat.status) {
        2 -> "充电中"
        3 -> "放电"
        5 -> "已满"
        else -> "状态码=${bat.status ?: "?"}"
    }
    fun sensor(name: String): String =
        th.sensors[name]?.let { v -> "%.1f°C".format(Locale.US, v) } ?: "—"

    return buildString {
        appendLine(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        appendLine(" 本轮快照  @$time")
        appendLine(" 系统判热: ${th.statusSummary}")
        appendLine(" 关键温度:  SKIN ${sensor("SKIN")}  |  AP ${sensor("AP")}  |  BAT ${sensor("BAT")}  |  USB ${sensor("USB")}  |  PA ${sensor("PA1THM")}")
        appendLine(" 电池:      $st  电量 $lvl  上报 $batTemp  ($chargeHint)")
        appendLine(" 性能负载:  1分钟负载≈$load1   CPU(估) $cpuStr   可用内存 $memStr   亮度 $brightness")
        appendLine(" 负载详情:  ${formatLoadAvgLine(loadavg)}")
        appendLine(" 前台:      ${fg.take(200)}${if (fg.length > 200) "…" else ""}")
        appendLine("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
    }
}

private data class ParsedBattery(
    val level: Int?,
    val tempC: Double?,
    val status: Int?,
    val health: Int?,
    val plugged: Int?,
)

private data class ParsedThermal(
    val statusCode: Int?,
    val statusSummary: String,
    val sensors: Map<String, Double>,
)

private fun parseBatterySnapshot(raw: String): ParsedBattery {
    val map = linkedMapOf<String, String>()
    for (line in raw.lineSequence()) {
        val t = line.trim()
        val idx = t.indexOf(':')
        if (idx <= 0) continue
        val k = t.substring(0, idx).trim().lowercase(Locale.getDefault())
        val v = t.substring(idx + 1).trim()
        map[k] = v
    }
    val tempDeci = map["temperature"]?.toIntOrNull()
    return ParsedBattery(
        level = map["level"]?.toIntOrNull(),
        tempC = tempDeci?.let { it / 10.0 },
        status = map["status"]?.toIntOrNull(),
        health = map["health"]?.toIntOrNull(),
        plugged = map["plugged"]?.toIntOrNull(),
    )
}

private val thermalStatusNames = mapOf(
    0 to "无热节流 (NONE)",
    1 to "轻度 (LIGHT)",
    2 to "中等 (MODERATE)",
    3 to "严重 (SEVERE)",
    4 to "危急 (CRITICAL)",
    5 to "紧急 (EMERGENCY)",
    6 to "即将关机 (SHUTDOWN)",
)

private val tempSensorRegex =
    Regex("""mValue=([\d.]+),\s*mType=\d+,\s*mName=([^,}]+)""")
private val thermalStatusLineRegex =
    Regex("""Thermal Status:\s*(\d+)""")

private fun parseThermalSnapshot(raw: String): ParsedThermal {
    val code = thermalStatusLineRegex.find(raw)?.groupValues?.getOrNull(1)?.toIntOrNull()
    val label = code?.let { c -> thermalStatusNames[c] ?: "未知码=$c" } ?: "未解析到 Thermal Status"
    val summary = if (code != null) "$label  (Thermal Status=$code)" else label
    val sensors = linkedMapOf<String, Double>()
    for (m in tempSensorRegex.findAll(raw)) {
        val v = m.groupValues[1].toDoubleOrNull() ?: continue
        val name = m.groupValues[2].trim()
        if (name.isNotEmpty()) sensors[name] = v
    }
    return ParsedThermal(code, summary, sensors)
}

private fun parseMemAvailableKb(meminfo: String): Long? =
    meminfo.lineSequence()
        .map { it.trim() }
        .firstOrNull { it.startsWith("MemAvailable:", true) }
        ?.substringAfter(':')
        ?.trim()
        ?.split(Regex("\\s+"))
        ?.firstOrNull()
        ?.toLongOrNull()

/** 解读 [loadavg] 一行（/proc/loadavg）：1/5/15 分钟平均负载、可运行/任务总数、最近 PID。 */
/**
 * 从 dumpsys 单行里提取 `包名/Activity`（ActivityRecord / Window / ACTIVITY 等格式）。
 */
private fun extractForegroundComponentLine(line: String): String? {
    val t = line.trim()
    if (t.isEmpty() || t.contains("topResumedActivity=null", ignoreCase = true)) return null

    Regex("""ActivityRecord\{[^\s]+\s+u\d+\s+(\S+/\S+)\s+t\d+""").find(t)?.let { m ->
        return sanitizeComponentToken(m.groupValues[1])
    }
    Regex("""Window\{[^\s]+\s+u\d+\s+(\S+/\S+)""").find(t)?.let { m ->
        return sanitizeComponentToken(m.groupValues[1])
    }
    Regex("""mCurrentFocus=[^u]*u\d+\s+(\S+/\S+)""").find(t)?.let { m ->
        return sanitizeComponentToken(m.groupValues[1])
    }
    Regex("""mFocusedApp[^u]*u\d+\s+(\S+/\S+)""").find(t)?.let { m ->
        return sanitizeComponentToken(m.groupValues[1])
    }
    Regex("""(?i)ACTIVITY\s+(\S+/\S+)\s""").find("$t ")?.let { m ->
        return sanitizeComponentToken(m.groupValues[1])
    }
    return null
}

private fun sanitizeComponentToken(raw: String): String {
    var s = raw.trim().trimEnd('}', ')', ']', '"', '\'')
    val cut = setOf(' ', '}', ')', '+')
    val end = s.indexOfFirst { it in cut }.let { i -> if (i < 0) s.length else i }
    s = s.substring(0, end)
    if (!s.contains('/')) return ""
    if (s.equals("null/null", ignoreCase = true)) return ""
    return s
}

private fun firstForegroundFromDump(text: String): String? =
    text.lineSequence().mapNotNull { extractForegroundComponentLine(it) }.firstOrNull { it.isNotEmpty() }

private fun formatLoadAvgLine(loadavg: String): String {
    val parts = loadavg.trim().split(Regex("\\s+"))
    if (parts.size < 5) {
        return "原始: ${loadavg.ifEmpty { "(空)" }}"
    }
    val l1 = parts[0]
    val l5 = parts[1]
    val l15 = parts[2]
    val runTotal = parts[3].split('/')
    val run = runTotal.getOrNull(0) ?: "?"
    val total = runTotal.getOrNull(1) ?: "?"
    val lastPid = parts[4]
    return "1分钟=$l1  5分钟=$l5  15分钟=$l15  可运行/任务总数=$run/$total  最近PID=$lastPid"
}

private fun timestamp(): String =
    LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))

private fun printSection(title: String, body: () -> String) {
    println("-- $title --")
    println(body().trimEnd())
}

private class AdbSession(private val serial: String?) {
    val serialOrNull: String? get() = serial

    fun assertShellOk(probe: String) {
        val out = shellText(probe).trim()
        if (!out.contains("ok", ignoreCase = true)) {
            error("adb shell 探测失败，输出: \"$out\"。请确认设备已连接且已授权 USB 调试。")
        }
    }

    fun formatBatterySummary(raw: String): String {
        val keys = listOf(
            "level", "scale", "temperature", "voltage",
            "status", "health", "plugged", "present",
            "technology", "current now", "charge counter",
        )
        val lines = raw.lineSequence()
            .map { it.trim() }
            .filter { line ->
                keys.any { key -> line.startsWith(key, ignoreCase = true) }
            }
            .distinctBy { line ->
                line.substringBefore(':').trim().lowercase(Locale.getDefault())
            }
            .toList()
        val formatted = lines.map { formatBatteryLine(it) }
        return if (formatted.isEmpty()) raw.take(800) else formatted.joinToString("\n")
    }

    fun formatThermalHead(raw: String): String {
        if (raw.isBlank()) return "(无输出，可能系统未暴露 thermalservice)"
        val head = raw.lineSequence().take(80).joinToString("\n")
        return head + if (raw.count { it == '\n' } > 80) "\n…(已截断)" else ""
    }

    fun thermalZoneSnapshot(): String {
        val cmd =
            "for d in /sys/class/thermal/thermal_zone*; do " +
                "test -f \"${'$'}d/temp\" && printf '%s %s\\n' \"${'$'}(tr -d '\\n'<\"${'$'}d/type\" 2>/dev/null)\" \"${'$'}(tr -d '\\n'<\"${'$'}d/temp\" 2>/dev/null)\"; " +
                "done 2>/dev/null | head -n 24"
        val out = shellText(cmd)
        return out.trim().ifEmpty { "(无法读取 /sys/class/thermal，可能被厂商限制)" }
    }

    fun cpuCurFreqSummary(): String {
        val cmd =
            "for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do " +
                "[ ! -f \"${'$'}f\" ] && continue; " +
                "hz=\"${'$'}(tr -d '\\n'<\"${'$'}f\" 2>/dev/null)\"; " +
                "n=\"${'$'}f\"; n=\"${'$'}{n#/sys/devices/system/cpu/}\"; n=\"${'$'}{n%%/*}\"; " +
                "mhz=\"${'$'}((hz/1000))\"; " +
                "printf '%s %s kHz (~%s MHz)\\n' \"${'$'}n\" \"${'$'}hz\" \"${'$'}mhz\"; " +
                "done 2>/dev/null | head -n 16"
        val out = shellText(cmd).trim()
        return if (out.isEmpty()) "(未读到 cpufreq 节点)" else out
    }

    fun cpuUsagePercent(): Int {
        fun parseCpuTimes(line: String): LongArray? {
            val s = line.trim()
            if (s.length < 5 || !s.startsWith("cpu") || !s[3].isWhitespace()) return null
            val parts = s.split(Regex("\\s+"))
            if (parts.size < 5) return null
            val nums = parts.drop(1).mapNotNull { p -> p.toLongOrNull() }
            if (nums.size < 4) return null
            return nums.toLongArray()
        }
        fun aggregateCpuLine(stat: String): String? =
            stat.lineSequence()
                .map { it.trim() }
                .firstOrNull { it.length >= 5 && it.startsWith("cpu") && it[3].isWhitespace() }
        val stat1 = shellText("cat /proc/stat")
        val line1 = aggregateCpuLine(stat1) ?: return -1
        val a = parseCpuTimes(line1) ?: return -1
        Thread.sleep(800)
        val line2 = aggregateCpuLine(shellText("cat /proc/stat")) ?: return -1
        val b = parseCpuTimes(line2) ?: return -1
        val idleDelta = b[3] - a[3]
        val totalDelta = b.sum() - a.sum()
        if (totalDelta <= 0L) return -1
        val usage = 100.0 * (1.0 - idleDelta.toDouble() / totalDelta.toDouble())
        return usage.roundToInt().coerceIn(0, 100)
    }

    fun memInfoSummary(): String {
        val keys = setOf("MemTotal:", "MemFree:", "MemAvailable:", "SwapTotal:", "SwapFree:")
        return shellText("cat /proc/meminfo")
            .lineSequence()
            .map { it.trim() }
            .filter { line -> keys.any { line.startsWith(it, ignoreCase = true) } }
            .joinToString("\n")
            .ifEmpty { "(未读到 /proc/meminfo)" }
    }

    fun foregroundComponent(): String {
        val sources = listOf(
            shellText(
                "dumpsys activity activities 2>/dev/null | grep -iE 'topResumedActivity|mResumedActivity|ResumedActivity' | head -n 24"
            ),
            shellText(
                "dumpsys window 2>/dev/null | grep -iE 'mCurrentFocus|mFocusedApp' | head -n 24"
            ),
            shellText(
                "dumpsys window displays 2>/dev/null | grep -iE 'mCurrentFocus|mFocusedApp' | head -n 24"
            ),
            shellText("dumpsys activity top 2>/dev/null | head -n 60"),
        )
        for (raw in sources) {
            firstForegroundFromDump(raw)?.let { return it }
        }
        return "(未能解析前台组件)"
    }

    /**
     * dumpsys cpuinfo 里进程行通常「高占用在前」，但末尾会是一大串 0% 系统线程；
     * 若只取 takeLast，会出现 TOTAL 很高但上面全是 0% 的错觉。这里解析占比后按从高到低排序。
     */
    fun dumpCpuInfoSummary(): String {
        val raw = shellText("dumpsys cpuinfo 2>/dev/null")
        if (raw.isBlank()) return "(dumpsys cpuinfo 无输出)"
        val processLine = Regex("""^\+?([\d.]+)%\s+(\d+)/(.+)$""")
        val totalLineRegex = Regex("""^\+?[\d.]+%\s+TOTAL:""", RegexOption.IGNORE_CASE)
        data class Row(val pct: Double, val text: String)
        val rows = mutableListOf<Row>()
        var totalLine: String? = null
        for (line in raw.lineSequence()) {
            val t = line.trim()
            if (t.isEmpty()) continue
            if (totalLineRegex.containsMatchIn(t)) {
                totalLine = t
                continue
            }
            val m = processLine.matchEntire(t) ?: continue
            val pct = m.groupValues[1].toDoubleOrNull() ?: 0.0
            rows += Row(pct, t)
        }
        val top = rows
            .sortedWith(compareByDescending<Row> { it.pct }.thenBy { it.text })
            .take(18)
        return buildString {
            appendLine("# 说明：与「列表在原文件中的顺序」无关；按本段统计里的占比排序。")
            if (top.isEmpty()) {
                appendLine(raw.lineSequence().filter { it.isNotBlank() }.take(30).joinToString("\n"))
            } else {
                top.forEach { appendLine(it.text) }
            }
            totalLine?.let { appendLine(it) }
        }
    }

    fun shellText(remoteCommand: String): String = runAdb("shell", remoteCommand)

    private fun runAdb(vararg command: String): String {
        val pb = ProcessBuilder().command(buildList {
            add("adb")
            serial?.let { addAll(listOf("-s", it)) }
            addAll(command.toList())
        })
        pb.redirectErrorStream(true)
        return try {
            val p = pb.start()
            val text = p.inputStream.bufferedReader().readText()
            val finished = p.waitFor(60, TimeUnit.SECONDS)
            if (!finished) {
                p.destroyForcibly()
                "(adb 超时)"
            } else if (p.exitValue() != 0 && text.isBlank()) {
                "(adb exit ${p.exitValue()})"
            } else {
                text
            }
        } catch (e: IOException) {
            "(执行失败: ${e.message})"
        }
    }

    companion object {
        fun resolve(): AdbSession {
            val fromEnv = System.getenv("ANDROID_SERIAL")?.trim()?.takeIf { it.isNotEmpty() }
            if (fromEnv != null) return AdbSession(fromEnv)
            val output = runAdbRaw(listOf("adb", "devices"))
            val devices = output.lines()
                .map { it.trim() }
                .filter { it.endsWith("\tdevice") }
                .map { it.substringBefore('\t').trim() }
                .filter { it.isNotEmpty() }
            return when (devices.size) {
                0 -> error(
                    "未检测到已授权的设备。请连接 USB、开启调试，并执行 `adb devices` 确认状态为 device。"
                )
                1 -> AdbSession(devices.first())
                else -> {
                    println("检测到多台设备，使用第一台: ${devices.first()}。可设置环境变量 ANDROID_SERIAL 指定。")
                    AdbSession(devices.first())
                }
            }
        }

        private fun runAdbRaw(args: List<String>): String {
            val pb = ProcessBuilder(args).redirectErrorStream(true)
            val p = pb.start()
            val text = p.inputStream.bufferedReader().readText()
            p.waitFor(30, TimeUnit.SECONDS)
            return text
        }
    }
}

private fun formatBatteryLine(line: String): String {
    val lower = line.lowercase(Locale.getDefault())
    return when {
        lower.startsWith("temperature") -> {
            val v = line.substringAfter(':', "").trim().toIntOrNull()
            if (v != null) {
                val c = v / 10.0
                "$line  (${"%.1f".format(Locale.US, c)} °C)"
            } else line
        }
        lower.startsWith("status") -> {
            val code = line.substringAfter(':', "").trim().toIntOrNull()
            val label = when (code) {
                1 -> "UNKNOWN"
                2 -> "CHARGING"
                3 -> "DISCHARGING"
                4 -> "NOT_CHARGING"
                5 -> "FULL"
                else -> null
            }
            if (label != null) "$line  ($label)" else line
        }
        lower.startsWith("health") -> {
            val code = line.substringAfter(':', "").trim().toIntOrNull()
            val label = when (code) {
                1 -> "UNKNOWN"
                2 -> "GOOD"
                3 -> "OVERHEAT"
                4 -> "DEAD"
                5 -> "OVER_VOLTAGE"
                6 -> "UNSPEC_FAILURE"
                7 -> "COLD"
                else -> null
            }
            if (label != null) "$line  ($label)" else line
        }
        lower.startsWith("plugged") -> {
            val code = line.substringAfter(':', "").trim().toIntOrNull()
            val label = when (code) {
                0 -> "ON_BATTERY"
                1 -> "AC"
                2 -> "USB"
                4 -> "WIRELESS"
                else -> null
            }
            if (label != null) "$line  ($label)" else line
        }
        else -> line
    }
}
