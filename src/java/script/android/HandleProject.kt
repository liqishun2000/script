package script.android

private const val targetProject: String = "E:\\code\\first\\app\\src\\main"
private val stringPrefix = listOf(
    "t_" to "new_",
    "text_" to "new_",
)
private val resPrefix = listOf(
    "t_" to "new_",
    "text_" to "new_",
)

//first为null size为1 则为添加前缀 替换前缀id格式为头分法
private val idPrefix = listOf(
    "" to "new",
)
//binding字段名
private val bindingNameList = listOf(
    "binding"
)

/**
 * 用于替换string资源名称，res目录下文件名，layout中的id名称
 * v1.1.0.0
 * */
fun main() {
    println("start handle...")
    val allFiles = getAllFiles(targetProject)

    replaceStringName(allFiles, stringPrefix)

    replaceResFileName(allFiles, resPrefix)

    replaceIdName(allFiles, idPrefix, bindingNameList)

    println("handle over")
}

fun String.containsExactMatch(target: String): Boolean {
    // 转义目标字符串中的特殊字符（如 .、$ 等）
    val escapedTarget = Regex.escape(target)
    // 构建正则表达式，使用单词边界确保精确匹配
    val regex = Regex("\\b$escapedTarget\\b")
    // 检查是否存在匹配项
    return regex.containsMatchIn(this)
}