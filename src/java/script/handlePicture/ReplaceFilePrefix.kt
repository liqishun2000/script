package script.handlePicture

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

fun main() {
    val parentFilePath = "E:\\tem\\图片"
    val sourcePrefix = "swipe_"
    val targetPrefix = "anv_ti_"

    val parentFile = File(parentFilePath)
    require(parentFile.isDirectory) { "不是有效目录: ${parentFile.absolutePath}" }

    val outPutFile = File(parentFile.absolutePath + "-output")
    outPutFile.mkdirs()

    val files = parentFile.listFiles()
        ?.filter { it.isFile }
        .orEmpty()

    if (files.isEmpty()) {
        println("未找到文件，目录: ${parentFile.absolutePath}")
        return
    }

    files.forEach { file ->
        val newName = computeNewName(file.name, sourcePrefix, targetPrefix)
        println("${file.name} -> $newName")

        val temFile = File(outPutFile.absolutePath + "\\$newName")
        val inputStream = FileInputStream(file)
        val outPutStream = FileOutputStream(temFile)

        val array = inputStream.readAllBytes()
        outPutStream.write(array)

        outPutStream.flush()
        inputStream.close()
        outPutStream.close()
    }

    println("处理完成，共 ${files.size} 个文件，输出目录: ${outPutFile.absolutePath}")
}

private fun computeNewName(fileName: String, sourcePrefix: String, targetPrefix: String): String {
    return if (fileName.startsWith(sourcePrefix)) {
        targetPrefix + fileName.drop(sourcePrefix.length)
    } else {
        targetPrefix + fileName
    }
}
