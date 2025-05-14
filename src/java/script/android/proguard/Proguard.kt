package script.android.proguard

import java.io.File
import java.io.FileOutputStream
import java.util.Random

/**
 * 生成混淆字典
 */
//字典样本
private val SOURCE: List<String> = mutableListOf<String>("c", "C", "u", "U")

//字典行数
private const val LENGTH = 5000

//输出路径
private const val ROOT_PATH =
    "C:\\Users\\fisrt\\AndroidStudioProjects\\script\\src\\java\\proguard"

//输出名称
private const val FILE_NAME = "output_dict.txt"

private val random = Random()


private fun main() {
    val unicodeList: List<String> = SOURCE
    val outputList: MutableList<String> = ArrayList()
    val file = File(ROOT_PATH, FILE_NAME)
    if (file.exists()) {
        println("文件已存在，删除")
        file.delete()
    } else {
        println("文件不存在")
    }

    val encoding = "UTF-8"
    var repeatCount = 0

    try {
        val fileOutputStream = FileOutputStream(file)
        var i = 0
        while (i < LENGTH) {
            var tmp = ""
            val width = random.nextInt(7) + 4
            for (j in 0 until width) {
                tmp += getRandomString(unicodeList)
            }
            if (!outputList.contains(tmp)) {
                i++
                outputList.add(tmp)
                fileOutputStream.write(tmp.toByteArray(charset(encoding)))
                if (i < LENGTH) {
                    //最后一行不输入回车
                    fileOutputStream.write('\n'.code)
                }
                repeatCount = 0
            } else {
                repeatCount++
                println("重复生成的字符串当前行数--->$i 内容---> $tmp")
                if (repeatCount == 10000) {
                    println("连续重复次数超过10000次 已达到最大行数 无法继续生成")
                    break
                }
            }
        }
        fileOutputStream.flush()
        fileOutputStream.close()
    } catch (e: Exception) {
        e.printStackTrace()
    }
}

private fun getRandomString(list: List<String?>): String? {
    val tm: String?
    val s = random.nextInt(list.size)
    tm = list[s]
    return tm
}
