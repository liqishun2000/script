package script.android

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

fun main() {
    val targetFileName = "easytsl_notification_button_s_"
    val suffixString = ".png"
    var targetIndex = 0

    val parentFile =
        File("E:\\WXData\\WXWork\\1688857010618043\\Cache\\File\\2025-05\\中按钮(8)\\中按钮")
    val outPutFile = File(parentFile.absolutePath + "-output")

    outPutFile.mkdirs()

    val files = parentFile.listFiles()!!
    files.forEachIndexed { index, file ->
        println("index:$index fileName:${file.name}")
        val temFile =
            File(outPutFile.absolutePath + "\\$targetFileName${extraNum(file.name)}$suffixString")
//            File(outPutFile.absolutePath + "\\$targetFileName${targetIndex}$suffixString")
        val inputStream = FileInputStream(file)
        val outPutStream = FileOutputStream(temFile)

        val array = inputStream.readAllBytes()
        outPutStream.write(array)

        outPutStream.flush()

        inputStream.close()
        outPutStream.close()

        targetIndex++

    }


}

private fun extraNum(name:String):String{
    val regex = Regex("""\d+""")
    val find = regex.find(name)
    return find?.value ?: ""
}
