package script.handlePicture

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

fun main() {

    val parentFile =
        File("E:\\tem\\翻书")
    val outPutFile = File(parentFile.absolutePath + "-output")

    outPutFile.mkdirs()

    val files = parentFile.listFiles()!!

    files.sortBy { extraNum(it.name).toInt() }

    val filter = files.filter { extraNum(it.name).toInt() % 3 == 0 }

    filter.forEachIndexed { index, file ->
        println("index:$index fileName:${file.name}")
        val temFile =
            File(outPutFile.absolutePath + "\\${file.name}")
//            File(outPutFile.absolutePath + "\\$targetFileName${targetIndex}$suffixString")
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
