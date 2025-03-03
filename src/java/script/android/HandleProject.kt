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

/**
 *
 * v1.0.0.1
 * */
fun main() {
    val allFiles = getAllFiles(targetProject)

    replaceStringName(allFiles, stringPrefix)

    replaceResFileName(allFiles, resPrefix)
}
