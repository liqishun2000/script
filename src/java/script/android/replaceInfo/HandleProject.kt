package script.android.replaceInfo

private const val targetProject: String = "E:\\code\\first\\app\\src\\main"
private val stringPrefix = listOf(
    "t_" to "new_",
    "text_" to "new_",
)
private val colorNamePrefix = listOf(
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

private val encodeInfo = listOf(
    //原来的appId appKey
    "" to "",
    //新的appId appKey
    "" to "",
)

//插入无用控件配置
val insertConfig = InsertConfig(
    /** 空行插入无用组件概率 0-100 */
    percent = 90..100,
    /** 无用ViewGroup最大嵌套层数 */
    maxLevel = 2,
    /** ViewGroup最大子View */
    maxChildNum = 5,
    /** 插入无用组件是ViewGroup组的概率 0-100 */
    createGroupProp = 25
)

/**
 * 用于替换string资源名称，res目录下文件名，layout中的id名称
 * v1.1.0.0
 * */
fun main() {
    println("start handle...")
    val allFiles = getAllFiles(targetProject)

    replaceStringName(allFiles, stringPrefix)
    replaceColorName(allFiles, colorNamePrefix)

    replaceResFileName(allFiles, resPrefix)

    replaceIdName(allFiles, idPrefix, bindingNameList)

    insertUselessCompose(allFiles)
//    replaceEncodeString(allFiles, encodeInfo)
    println("handle over")
}
