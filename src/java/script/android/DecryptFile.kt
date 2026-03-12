package script.android

import script.android.replaceInfo.aesDecrypt
import script.android.replaceInfo.md5
import java.io.File

private const val targetDirectory = "E:\\code\\daily-bible\\app\\src\\main\\assets\\prayer\\daily_sen"
private val appInfoPair = "1982494894" to "8abf1e04f2be455b8fcf54b00e416d6e"

/** 解密文件 */
fun main() {
    println("replace encode string...")

    traversalFilesAndHandle(File(targetDirectory))

    println("replace encode string over")
}

private fun traversalFilesAndHandle(file: File){
    if (file.isFile) {
        replaceEncodeString(file)
        return
    }


    if (file.isDirectory) {
        file.listFiles()?.forEach {
            traversalFilesAndHandle(it)
        }
    }
}


private fun replaceEncodeString(file: File){

    val key = getKey(appInfoPair)

    val readText = file.readText()
    var handleString = readText
    runCatching {
        handleString.aesDecrypt(key)
    }.onSuccess {
        handleString = it
    }

    file.writeText(handleString)

}

private fun replaceQuotedStrings(
    content: String,
    replaceRule: (original: String) -> String // 自定义替换规则
): String {
    val regex = "\"([^\"]*)\"".toRegex()
    return regex.replace(content) { matchResult ->
        val originalValue = matchResult.groupValues[1]
        if(originalValue.isBlank()){
            "\"$originalValue\""
        }else{
            val newValue = replaceRule(originalValue) // 根据规则生成新值
            "\"$newValue\"" // 保持双引号结构，替换内部内容
        }
    }
}

private fun extractQuotedStrings(content: String): List<String> {
    val regex = "\"([^\"]*)\"".toRegex() // 匹配双引号内的任意字符
    return regex.findAll(content)
        .map { it.groupValues[1] }      // 提取第一个捕获组（即双引号内的内容）
        .toList()
}


private fun getKey(pair:Pair<String,String>):String{
    return "${pair.first}${pair.second}".md5().substring(0,16)
}