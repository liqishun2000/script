package script.android

import java.io.File

private const val targetDirectory = "E:\\code\\script\\src"

fun main() {

    traversalFilesAndHandle(File(targetDirectory))
}

private fun traversalFilesAndHandle(file: File){
    if (file.isFile) {
        handleFIle(file)
        return
    }


    if (file.isDirectory) {
        file.listFiles()?.forEach {
            traversalFilesAndHandle(it)
        }
    }
}

private fun handleFIle(file:File){

    val readText = file.readText()
    val regex = Regex("[\\u4e00-\\u9fa5]")
    if(regex.containsMatchIn(readText)){
        println(file.name)
    }
}
