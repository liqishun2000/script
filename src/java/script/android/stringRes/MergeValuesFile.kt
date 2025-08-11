package script.android.stringRes

import java.io.File

private const val targetProjectResFilePath = "C:\\Users\\fisrt\\StudioProjects\\overseas-lx-xpx-sweep\\app\\src\\main\\res"
private const val endFlag = "</resources>"
private const val targetFileName = "strings.xml"

//翻译文本添加到文件中
private fun main() {
    val resFile = File(targetProjectResFilePath)
    val valuesFiles = resFile.listFiles()?.filter { it.name.contains("values-") && !it.name.contains("night") }

    if (valuesFiles == null) {
        println("there is no values- file")
        return
    }
    for(i in valuesFiles.indices){
        val valueFile = valuesFiles[i]

        var childFiles = valueFile.listFiles()

        if(childFiles.isNullOrEmpty()){
            println("${valueFile.absolutePath} has no child")
            continue
        }

        var hasTargetFile = false
        childFiles.find { it.name == targetFileName }?.let {
            hasTargetFile = true
        }

        if(hasTargetFile && childFiles.size == 1){
            continue
        }

        if(!hasTargetFile){
            val file = File("${valueFile.absolutePath}\\$targetFileName")
            file.createNewFile()
            val origin = """
                <?xml version="1.0" encoding="UTF-8"?><resources>
                </resources>
            """.trimIndent()
            file.writeText(origin)
        }

        childFiles = valueFile.listFiles()!!
        val singleFile = childFiles.find { it.name == targetFileName }!!

        childFiles.forEach { file->
            if(file.name != targetFileName){
                val lines = file.readLines().filter { it.contains("<string") && it.contains("</string>") }
                insertLinesBeforeLastTag(singleFile,lines)
                file.delete()
            }
        }
    }
}

private fun insertLinesBeforeLastTag(file: File, newLines: List<String>) {
    val lines = file.readLines().toMutableList()

    when {
        lines.last().contains(endFlag) -> {
            // 在结尾标识前批量插入多行
            lines.addAll(lines.lastIndex, newLines)
        }
        else -> {
            // 无结尾标识时在文件末尾插入
            lines.addAll(newLines)
        }
    }

    // 保持原文件换行格式
    file.writeText(lines.joinToString("\n"))
}
