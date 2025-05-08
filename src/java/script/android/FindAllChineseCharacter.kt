package script.android

import java.io.File

private const val targetDirectory = "C:\\Users\\fisrt\\AndroidStudioProjects\\qrscanner-basedscanner"

fun main() {

    traversalFilesAndHandle(File(targetDirectory))
}

private fun traversalFilesAndHandle(file: File){
    if (file.isFile) {
        handleFIle(file)
        return
    }


    if (file.isDirectory) {
        if(canSearch(file)){
            file.listFiles()?.forEach {
                traversalFilesAndHandle(it)
            }
        }
    }
}

private fun canSearch(file: File):Boolean{
    val list = listOf(
        ".gradle",
        ".idea",
        "name",
        "build",
        ".git",
        "drawable-xhdpi",
        "assets",
    )
    list.find { it == file.name } ?: return true

    return false
}

private fun handleFIle(file:File){

    val readText = file.readText()
    val regex = Regex("[\\u4e00-\\u9fa5]")
    if(regex.containsMatchIn(readText)){
        println(file.absolutePath)
    }
}
