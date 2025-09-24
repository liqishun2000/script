package script.webhook

import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL


import java.util.Base64
import java.security.MessageDigest

fun main() {
    val webhookUrl = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=9e3de4e3-b5a3-499d-98b8-75406bba434e"
    simpleTest()

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
}

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