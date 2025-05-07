package script.android

import script.android.replaceInfo.aesDecrypt
import script.android.replaceInfo.aesEncrypt
import script.android.replaceInfo.md5
import java.io.File
import java.util.regex.Pattern

private const val targetDirectory = ""
private val appInfoPair = "appId" to "appKey"
private const val decodeFunction = ".dec()"

/** 加密整个目录或文件下所有的未加密过的字符串 并添加解密方法 */
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
    val userRegex = Regex("""(\$\{[^}]+}|\$\w+)""")
    val newText = replaceQuotedStrings(readText) { origin ->
        var handleString = origin
        runCatching {
            handleString.aesDecrypt(key)
        }.onFailure {
            val list = splitWithSeparators(handleString,userRegex)

            if(userRegex.containsMatchIn(handleString)){
                handleString = list.joinToString("", prefix = "\"", postfix = "\""){ part->
                    if(userRegex.matches(part)){
                        part
                    }else{
                        """${"$"}{"${part.aesEncrypt(key)}"${decodeFunction}}"""
                    }
                }
            }else{
                """"${handleString.aesEncrypt(key)}"$decodeFunction"""
            }
        }

        handleString
    }
    file.writeText(newText)

}

private fun splitWithSeparators(input: String, regex: Regex): List<String> {
    val pattern = Pattern.compile("(${regex.pattern})")
    val matcher = pattern.matcher(input)
    val parts = mutableListOf<String>()
    var lastEnd = 0
    while (matcher.find()) {
        val start = matcher.start()
        if (start > lastEnd) {
            parts.add(input.substring(lastEnd, start))
        }
        parts.add(matcher.group())
        lastEnd = matcher.end()
    }
    if (lastEnd < input.length) {
        parts.add(input.substring(lastEnd))
    }
    return parts
}

private fun replaceQuotedStrings(
    content: String,
    replaceRule: (original: String) -> String // 自定义替换规则
): String {
    val regex = "\"([^\"]*)\"".toRegex()
    val newValueMap:MutableMap<String,String> = mutableMapOf()

    val result = regex.replace(content) { matchResult ->
        val originalValue = matchResult.groupValues[1]
        if(originalValue.disableEncrypt()){
            "\"$originalValue\""
        }else{
            val newValue = replaceRule(originalValue) // 根据规则生成新值
            return@replace if(originalValue != newValue){
                newValueMap[originalValue] = newValue
                newValue
            }else "\"$newValue\"" // 保持双引号结构，替换内部内容
        }
    }

    if(newValueMap.isNotEmpty()){
        val newResultList = mutableListOf<String>()
        val split = result.split("\r\n")
        split.forEach { line->
            newValueMap.forEach { (key,value)->
                if(line.contains(value)){
                    val blankNum = line.takeWhile { it.isWhitespace() }.length
                    newResultList.add("""${" ".repeat(blankNum)}//$key""")
                }
            }
            newResultList.add(line)
        }
        return newResultList.joinToString("\r\n")
    }

    return result
}

private fun String.disableEncrypt(): Boolean {
    val regex = Regex("""\w+""")
    return !regex.containsMatchIn(this)
            || this == "SetTextI18n"
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