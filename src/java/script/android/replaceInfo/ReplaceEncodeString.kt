package script.android.replaceInfo

import java.io.File

fun replaceEncodeString(allFiles: ProjectBean, encodeInfo:List<Pair<String,String>>){
    println("replace encode string...")

    val originKey = getKey(encodeInfo[0])
    val targetKey = getKey(encodeInfo[1])

    allFiles.javaFiles.forEach { path->
        val file = File(path)
        val readText = file.readText()
        val newText = replaceQuotedStrings(readText){ origin->
            var handleString = origin
            runCatching {
                handleString.aesDecrypt(originKey)
            }.onSuccess { decryptString->
                handleString = decryptString.aesEncrypt(targetKey)
            }

            handleString
        }
        file.writeText(newText)
    }

    println("replace encode string over")
}

fun replaceQuotedStrings(
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