package script.handlePicture

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

fun main() {

    val targetFileName = "bible_open_book_"
    val suffix = ".png"

    val parentFile =
        File("E:\\tem\\翻书1")
    val outPutFile = File(parentFile.absolutePath + "-output")

    outPutFile.mkdirs()

    val files = parentFile.listFiles()!!

    files.sortBy { extraNum(it.name).toInt() }

    files.forEachIndexed { index, file ->
        println("index:$index fileName:${file.name}")
        val temFile =
            File(outPutFile.absolutePath + "\\$targetFileName${index.toString().formatNum()}$suffix")
        val inputStream = FileInputStream(file)
        val outPutStream = FileOutputStream(temFile)

        val array = inputStream.readAllBytes()
        outPutStream.write(array)

        outPutStream.flush()

        inputStream.close()
        outPutStream.close()


    }


}

private fun String.formatNum(): String{
    return String.format("%02d",this.toInt())
}

private fun extraNum(name:String):String{
    val regex = Regex("""\d+""")
    val find = regex.find(name)
    return find?.value ?: ""
}
