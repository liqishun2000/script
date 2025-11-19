package script.webhook

import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL


import java.util.Base64
import java.security.MessageDigest

fun main() {
    val webhookUrl = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9e3de4e3-b5a3-499d-98b8-75406bba434e"
//    simpleTest()

    mainUpgradeTest()


    //region demo测试
    // 发送文本消息
//    sendWechatMessage(
//        webhookUrl = webhookUrl,
//        msgType = "text",
//        content = "这是一条文本消息",
//        mentionedUserIds = listOf("zhangsan")
//    )

    // 发送Markdown消息
//    sendWechatMessage(
//        webhookUrl = webhookUrl,
//        msgType = "markdown",
//        content = "**Markdown消息**\n" +
//                "> 这是一条Markdown消息\n" +
//                "> - 项目1\n" +
//                "> - 项目2\n" +
//                "> [点击查看详情](https://work.weixin.qq.com)"
//    )

    // 发送图片消息
//    sendWechatMessage(
//        webhookUrl = webhookUrl,
//        msgType = "image",
//        imagePath = "path/to/your/image.jpg" // 替换为实际图片路径
//    )

    // 发送图文卡片消息
//    sendWechatMessage(
//        webhookUrl = webhookUrl,
//        msgType = "news",
//        articles = listOf(
//            Article(
//                title = "企业微信更新公告",
//                description = "最新功能发布，点击查看详情",
//                url = "https://work.weixin.qq.com",
//                picUrl = "https://haowallpaper.com/link/common/file/previewFileImg/15758358777205056"
//            ),
//            Article(
//                title = "API文档",
//                description = "机器人API使用指南",
//                url = "https://work.weixin.qq.com/api/doc",
//                picUrl = "https://haowallpaper.com/link/common/file/previewFileImg/15758358777205056"
//            )
//        )
//    )
    //endregion
}

//region demo
// 图文卡片消息结构
data class Article(
    val title: String,
    val description: String,
    val url: String,
    val picUrl: String
)

fun sendWechatMessage(
    webhookUrl: String,
    msgType: String,
    content: String? = null,
    mentionedUserIds: List<String>? = null,
    mentionedMobiles: List<String>? = null,
    mentionAll: Boolean = false,
    imagePath: String? = null,
    articles: List<Article>? = null
) {
    if (!webhookUrl.startsWith("http")) {
        throw IllegalArgumentException("Webhook URL must start with http:// or https://")
    }

    val jsonPayload = when (msgType) {
        "text" -> buildTextJsonPayload(content, mentionedUserIds, mentionedMobiles, mentionAll)
        "markdown" -> buildMarkdownJsonPayload(content)
        "image" -> buildImageJsonPayload(imagePath)
        "news" -> buildNewsJsonPayload(articles)
        else -> throw IllegalArgumentException("Unsupported message type: $msgType")
    }

    try {
        val url = URL(webhookUrl)
        val conn = url.openConnection() as HttpURLConnection
        conn.apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=UTF-8")
            connectTimeout = 5000
            readTimeout = 5000
        }

        OutputStreamWriter(conn.outputStream, "UTF-8").use { writer ->
            writer.write(jsonPayload)
            writer.flush()
        }

        val responseCode = conn.responseCode
        if (responseCode in 200..299) {
            println("$msgType 消息发送成功")
        } else {
            println("$msgType 消息发送失败，HTTP状态码: $responseCode")
            conn.errorStream?.bufferedReader()?.use {
                println("错误响应: ${it.readText()}")
            }
        }
    } catch (e: Exception) {
        println("发送 $msgType 消息时出错: ${e.message}")
        e.printStackTrace()
    }
}

// 构建文本消息JSON
private fun buildTextJsonPayload(
    content: String?,
    mentionedUserIds: List<String>?,
    mentionedMobiles: List<String>?,
    mentionAll: Boolean
): String {
    val mentionedList = mutableListOf<String>().apply {
        if (mentionAll) add("@all")
        mentionedUserIds?.let { addAll(it) }
    }
    val mentionedMobileList = mentionedMobiles?.toList() ?: emptyList()

    // 构建消息内容（包含@信息）
    val mentionText = buildString {
        mentionedList.filter { it != "@all" }.forEach { append("<@$it> ") }
        mentionedMobileList.forEach { append("<@$it> ") }
        if (mentionAll) append("@all ")
    }.trim()

    val fullContent = if (mentionText.isNotEmpty()) "$mentionText\n${content ?: ""}" else (content ?: "")

    return """
        {
            "msgtype": "text",
            "text": {
                "content": "$fullContent",
                ${if (mentionedList.isNotEmpty()) "\"mentioned_list\": ${mentionedList.toJsonString()}," else ""}
                ${if (mentionedMobileList.isNotEmpty()) "\"mentioned_mobile_list\": ${mentionedMobileList.toJsonString()}," else ""}
            }
        }
    """.trimIndent().replace(",\n            }", "\n            }") // 移除最后一个逗号
}

// 构建Markdown消息JSON
private fun buildMarkdownJsonPayload(content: String?): String {
    return """
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "${content?.escapeJson()}"
            }
        }
    """.trimIndent()
}

// 构建图片消息JSON
private fun buildImageJsonPayload(imagePath: String?): String {
    if (imagePath == null) throw IllegalArgumentException("Image path is required for image messages")

    val (base64, md5) = getImageBase64AndMd5(imagePath) ?: throw Exception("Failed to read image")

    return """
        {
            "msgtype": "image",
            "image": {
                "base64": "$base64",
                "md5": "$md5"
            }
        }
    """.trimIndent()
}

// 构建图文卡片消息JSON
private fun buildNewsJsonPayload(articles: List<Article>?): String {
    if (articles.isNullOrEmpty()) throw IllegalArgumentException("Articles are required for news messages")

    val articlesJson = articles.joinToString(",\n") { article ->
        """
        {
            "title": "${article.title.escapeJson()}",
            "description": "${article.description.escapeJson()}",
            "url": "${article.url.escapeJson()}",
            "picurl": "${article.picUrl.escapeJson()}"
        }
        """.trimIndent()
    }

    return """
        {
            "msgtype": "news",
            "news": {
                "articles": [
                    $articlesJson
                ]
            }
        }
    """.trimIndent()
}


// 辅助函数：JSON转义
private fun String.escapeJson(): String {
    return this
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
}

// 读取图片并计算Base64和MD5
private fun getImageBase64AndMd5(filePath: String): Pair<String, String>? {
    return try {
        val file = java.io.File(filePath)
        if (!file.exists()) {
            println("文件不存在: $filePath")
            return null
        }
        val bytes = file.readBytes()
        val base64 = Base64.getEncoder().encodeToString(bytes)
        val md5 = MessageDigest.getInstance("MD5").digest(bytes).joinToString("") { "%02x".format(it) }
        Pair(base64, md5)
    } catch (e: Exception) {
        e.printStackTrace()
        null
    }
}
//endregion

//region 指定用户
private fun designateUser() {
    val webhookUrl = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9e3de4e3-b5a3-499d-98b8-75406bba434e"

    // 普通消息
//    sendWechatMessage(webhookUrl, "普通通知消息")

    // @指定成员（通过用户ID）
    sendWechatMessage(webhookUrl, "script test!", mentionedUserIds = listOf("liqishun@hopemobi.com"))

//    // @指定成员（通过手机号）
//    sendWechatMessage(webhookUrl, "请尽快处理", mentionedMobiles = listOf("13800138000", "13900139000"))
//
//    // @所有人
//    sendWechatMessage(webhookUrl, "全体成员请注意", mentionAll = true)
}

private fun sendWechatMessage(
    webhookUrl: String,
    content: String,
    mentionedUserIds: List<String>? = null,
    mentionedMobiles: List<String>? = null,
    mentionAll: Boolean = false
) {
    if (!webhookUrl.startsWith("http")) {
        throw IllegalArgumentException("Webhook URL must start with http:// or https://")
    }

    // 构建@人信息
    val mentionText = buildString {
        mentionedUserIds?.forEach { append("<@$it> ") }
        mentionedMobiles?.forEach { append("<@$it> ") }
        if (mentionAll) append("@all ")
    }.trim()

    // 完整的消息内容
    val fullContent = if (mentionText.isNotEmpty()) "$mentionText\n$content" else content

    // 构建JSON请求体
    val jsonPayload = buildJsonPayload(fullContent, mentionedUserIds, mentionedMobiles, mentionAll)

    try {
        val url = URL(webhookUrl)
        val conn = url.openConnection() as HttpURLConnection
        conn.apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=UTF-8")
            connectTimeout = 5000
            readTimeout = 5000
        }

        OutputStreamWriter(conn.outputStream, "UTF-8").use { writer ->
            writer.write(jsonPayload)
            writer.flush()
        }

        val responseCode = conn.responseCode
        if (responseCode in 200..299) {
            println("消息发送成功")
        } else {
            println("消息发送失败，HTTP状态码: $responseCode")
            conn.errorStream?.bufferedReader()?.use {
                println("错误响应: ${it.readText()}")
            }
        }
    } catch (e: Exception) {
        println("发送消息时出错: ${e.message}")
        e.printStackTrace()
    }
}

private fun buildJsonPayload(
    content: String,
    mentionedUserIds: List<String>?,
    mentionedMobiles: List<String>?,
    mentionAll: Boolean
): String {
    val mentionedList = mutableListOf<String>().apply {
        if (mentionAll) add("@all")
        mentionedUserIds?.let { addAll(it) }
    }

    val mentionedMobileList = mentionedMobiles?.toList() ?: emptyList()

    return """
        {
            "msgtype": "text",
            "text": {
                "content": "$content",
                ${if (mentionedList.isNotEmpty()) "\"mentioned_list\": ${mentionedList.toJsonString()}," else ""}
                ${if (mentionedMobileList.isNotEmpty()) "\"mentioned_mobile_list\": ${mentionedMobileList.toJsonString()}," else ""}
            }
        }
    """.trimIndent().replace(",\n            }", "\n            }") // 移除最后一个逗号
}

// 辅助函数：将列表转换为JSON数组字符串
private fun List<String>.toJsonString(): String {
    return if (isEmpty()) "[]" else "[\"${joinToString("\", \"")}\"]"
}
//endregion

//region upgrade test

data class WechatMessage(
    val msgtype: String,
    val text: TextContent? = null,
    val markdown: MarkdownContent? = null
)

data class TextContent(
    val content: String,
    val mentioned_list: List<String>? = null,
    val mentioned_mobile_list: List<String>? = null
)

data class MarkdownContent(
    val content: String
)

class WechatBot(private val webhookUrl: String) {

    /**
     * 发送文本消息（支持@功能）
     */
    fun sendTextMessage(content: String, mentionedList: List<String>? = null, mentionedMobileList: List<String>? = null): Boolean {
        val message = WechatMessage(
            msgtype = "text",
            text = TextContent(content, mentionedList, mentionedMobileList)
        )
        return sendMessage(message)
    }

    /**
     * 发送Markdown消息（支持高亮、格式化）
     */
    fun sendMarkdownMessage(content: String): Boolean {
        val message = WechatMessage(
            msgtype = "markdown",
            markdown = MarkdownContent(content)
        )
        return sendMessage(message)
    }

    /**
     * 发送带高亮的成功消息
     */
    fun sendSuccessMessage(title: String, content: String, highlightItems: List<String> = emptyList()): Boolean {
        val markdownContent = buildMarkdownContent(title, content, highlightItems, "success")
        return sendMarkdownMessage(markdownContent)
    }

    /**
     * 发送带高亮的警告消息
     */
    fun sendWarningMessage(title: String, content: String, highlightItems: List<String> = emptyList()): Boolean {
        val markdownContent = buildMarkdownContent(title, content, highlightItems, "warning")
        return sendMarkdownMessage(markdownContent)
    }

    /**
     * 发送带高亮的错误消息
     */
    fun sendErrorMessage(title: String, content: String, highlightItems: List<String> = emptyList()): Boolean {
        val markdownContent = buildMarkdownContent(title, content, highlightItems, "error")
        return sendMarkdownMessage(markdownContent)
    }

    /**
     * 发送带高亮的信息消息
     */
    fun sendInfoMessage(title: String, content: String, highlightItems: List<String> = emptyList()): Boolean {
        val markdownContent = buildMarkdownContent(title, content, highlightItems, "info")
        return sendMarkdownMessage(markdownContent)
    }

    private fun buildMarkdownContent(title: String, content: String, highlightItems: List<String>, type: String): String {
        val emoji = when (type) {
            "success" -> "✅"
            "warning" -> "⚠️"
            "error" -> "❌"
            else -> "ℹ️"
        }

        val titleColor = when (type) {
            "success" -> "info"  // 绿色
            "warning" -> "warning"  // 黄色
            "error" -> "danger"  // 红色
            else -> "comment"  // 灰色
        }

        val builder = StringBuilder()
        builder.append("<font color=\"$titleColor\">**$emoji $title**</font>\n\n")
        builder.append("$content\n\n")

        if (highlightItems.isNotEmpty()) {
            builder.append("**高亮信息:**\n")
            highlightItems.forEach { item ->
                builder.append("> • <font color=\"warning\">$item</font>\n")
            }
        }

        return builder.toString()
    }

    private fun sendMessage(message: WechatMessage): Boolean {
        val jsonPayload = when (message.msgtype) {
            "text" -> """
                {
                    "msgtype": "text",
                    "text": {
                        "content": "${escapeJson(message.text?.content ?: "")}",
                        ${if (!message.text?.mentioned_list.isNullOrEmpty()) "\"mentioned_list\": ${message.text.mentioned_list.toJsonString()}," else ""}
                        ${if (!message.text?.mentioned_mobile_list.isNullOrEmpty()) "\"mentioned_mobile_list\": ${message.text.mentioned_mobile_list.toJsonString()}," else ""}
                    }
                }
            """.trimIndent().replace(",\n}", "\n}")  // 移除尾随逗号

            "markdown" -> """
                {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": "${escapeJson(message.markdown?.content ?: "")}"
                    }
                }
            """.trimIndent()

            else -> throw IllegalArgumentException("不支持的消息类型: ${message.msgtype}")
        }

        return sendRequest(jsonPayload)
    }

    private fun escapeJson(text: String): String {
        return text.replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
    }

    private fun sendRequest(jsonPayload: String): Boolean {
        try {
            val url = URL(webhookUrl)
            val conn = url.openConnection() as HttpURLConnection
            conn.apply {
                requestMethod = "POST"
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=UTF-8")
                connectTimeout = 5000
                readTimeout = 5000
            }

            OutputStreamWriter(conn.outputStream, "UTF-8").use { writer ->
                writer.write(jsonPayload)
                writer.flush()
            }

            val responseCode = conn.responseCode
            if (responseCode in 200..299) {
                println("消息发送成功")
                return true
            } else {
                println("消息发送失败，HTTP状态码: $responseCode")
                conn.errorStream?.bufferedReader()?.use {
                    println("错误响应: ${it.readText()}")
                }
                return false
            }
        } catch (e: Exception) {
            println("发送消息时出错: ${e.message}")
            e.printStackTrace()
            return false
        }
    }
}

// 使用示例
fun mainUpgradeTest() {
    val webhookUrl = "\n" +
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=f958b257-788a-47b6-833f-70bce94e24b9"
    val bot = WechatBot(webhookUrl)

    // 1. 发送简单文本消息
//    bot.sendTextMessage("这是一条普通文本消息")

    // 2. 发送@特定用户的消息
//    bot.sendTextMessage(
//        content = "<@liqishun@hopemobi.com>这是一条@所有人的消息",
//        mentionedList = listOf("liqishun@hopemobi.com")
//    )

//    // 3. 发送带高亮的成功消息
    bot.sendSuccessMessage(
        title = "部署成功",
        content = "项目部署完成，服务运行正常",
        highlightItems = listOf("部署时间: 2024-01-01 10:00:00", "版本: v1.2.3", "环境: 生产环境")
    )
//
//    // 4. 发送带高亮的错误消息
//    bot.sendErrorMessage(
//        title = "系统异常",
//        content = "检测到服务异常，请及时处理",
//        highlightItems = listOf("错误代码: 500", "服务名称: user-service", "发生时间: 2024-01-01 10:05:00")
//    )
//
    // 5. 发送自定义Markdown消息（支持更复杂的高亮格式）
    val customMarkdown = """
        **项目状态报告**

        > **构建状态:** <font color="info">成功</font>
        > **测试覆盖率:** <font color="warning">85%</font>
        > **代码质量:** <font color="comment">A级</font>

        **关键指标:**
        - 性能: ⚡️ <font color="info">优秀</font>
        - 安全性: 🔒 <font color="warning">良好</font>
        - 稳定性: 🏗️ <font color="info">优秀</font>
    """.trimIndent()

    bot.sendMarkdownMessage(customMarkdown)
}
//endregion

//region simple test
private fun simpleTest() {
    // 确保URL以https://开头
    val webhookUrl = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9e3de4e3-b5a3-499d-98b8-75406bba434e"
//    val message = "Hello from Kotlin! 当前时间：${System.currentTimeMillis()}"
    val message = "initTime:2025:09:22 18:36:14"

    sendWechatGroupMessage(webhookUrl, message)
}

private fun sendWechatGroupMessage(webhookUrl: String, content: String) {
    // 添加URL格式检查
    if (!webhookUrl.startsWith("http")) {
        throw IllegalArgumentException("Webhook URL must start with http:// or https://")
    }

    val jsonPayload = """
        {
            "msgtype": "text",
            "text": {
                "content": "$content"
            }
        }
    """.trimIndent()

    try {
        val url = URL(webhookUrl)
        val conn = url.openConnection() as HttpURLConnection
        conn.apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=UTF-8")
            connectTimeout = 5000
            readTimeout = 5000
        }

        OutputStreamWriter(conn.outputStream, "UTF-8").use { writer ->
            writer.write(jsonPayload)
            writer.flush()
        }

        val responseCode = conn.responseCode
        if (responseCode in 200..299) {
            println("消息发送成功")
        } else {
            println("消息发送失败，HTTP状态码: $responseCode")
            conn.errorStream?.bufferedReader()?.use {
                println("错误响应: ${it.readText()}")
            }
        }
    } catch (e: Exception) {
        println("发送消息时出错: ${e.message}")
        e.printStackTrace()
    }
}
//endregion