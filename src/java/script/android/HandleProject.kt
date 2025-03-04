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
 *
 * v1.0.0.1
 * */
fun main() {
    val allFiles = getAllFiles(targetProject)

    replaceStringName(allFiles, stringPrefix)

    replaceResFileName(allFiles, resPrefix)

    replaceIdName(allFiles, idPrefix, bindingNameList)
}
