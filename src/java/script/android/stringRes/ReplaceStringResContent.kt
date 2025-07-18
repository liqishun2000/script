package script.android.stringRes

import java.io.File

private const val translationFilePath = "E:\\work\\scanner\\1.2.0.0\\QR二维码翻译 V1.2.0.0\\QR二维码翻译 V1.2.0.0"
private const val targetProjectResFilePath = "E:\\tem\\res"
private const val endFlag = "</resources>"

//替换string.xml中相同name的content
private fun main() {
    val languageFileMap = getLanguageFile()

    val resFile = File(targetProjectResFilePath)
    val valuesFiles = resFile.listFiles()?.filter { it.name.contains("values-") }

    valuesFiles?.forEach{ valuesFile->
        languageFileMap.toList().forEach { pair->
            if(valuesFile.name.contains(pair.first)){
                val needAddString = pair.second.bufferedReader(Charsets.UTF_8).use { reader ->
                    // 手动处理BOM
                    val firstLine = reader.readLine()?.removePrefix("\uFEFF") ?: ""
                    val remainingLines = reader.readLines()

                    listOf(firstLine) + remainingLines
                }.map { string ->
                    //移除特殊空格
                    var handleString = string.replace("[\u00A0\u200B]".toRegex(), "")
                    //添加转义字符
                    handleString = addBackslashBeforeSingleQuote(handleString)
                    // & 替换为 &amp;
                    handleString = replaceAnd(handleString)

                    "    ${handleString}"
//                    "    $string" // 添加缩进
                }
                val stringFile = valuesFile.listFiles()!!.first()
                insertLinesBeforeLastTag(stringFile,needAddString)
            }
        }

    }

}

private fun replaceAnd(input: String): String {
    val result = StringBuilder()
    for (i in input.indices) {
        val currentChar = input[i]
        if (currentChar == '&') {
            if (i + 1 < input.length && input[i + 1] != 'a') {
                result.append("&amp;")
                continue
            }
        }
        result.append(currentChar)
    }
    return result.toString()
}

private fun addBackslashBeforeSingleQuote(input: String): String {
    val result = StringBuilder()
    for (i in input.indices) {
        val currentChar = input[i]
        if (currentChar == '\'') {
            // 检查前一个字符是否是反斜杠
            if (i == 0 || input[i - 1] != '\\') {
                result.append('\\')
            }
        }
        result.append(currentChar)
    }
    return result.toString()
}

private fun insertLinesBeforeLastTag(file: File, newLines: List<String>) {
    val lines = file.readLines().toMutableList()
    val regex = Regex(""">([^<]+)</""")
    for(i in lines.indices){
        val origin = lines[i]
        val originName = extractNameAttribute(origin)
        newLines.forEach { newContent->
            val newName = extractNameAttribute(newContent)
            if(!originName.isNullOrBlank() && !newName.isNullOrBlank() && newName == originName){
                extractContentAttribute(newContent)?.let { newValue->
                    val handleString = regex.replace(origin,">$newValue</")
                    lines[i] = handleString
                    return@forEach
                }
            }
        }
    }

    // 保持原文件换行格式
    file.writeText(lines.joinToString("\n"))
}


private fun extractNameAttribute(xmlString: String): String? {
    val pattern = Regex("""name=["']([^"']+)["']""")
    val matchResult = pattern.find(xmlString)
    return matchResult?.groupValues?.get(1)
}

private fun extractContentAttribute(xmlString: String): String? {
    val pattern = Regex(""">([^<]+)</""")
    val matchResult = pattern.find(xmlString)
    return matchResult?.groupValues?.get(1)
}
private fun getLanguageFile():Map<String,File>{
    val origin = File(translationFilePath)
    val listFiles = origin.listFiles()

    val map:MutableMap<String,File> = mutableMapOf()
    listFiles.forEach { listFile->
        val suffix = listFile.name.substring(listFile.name.lastIndexOf("."))
        val name = listFile.name.replace(suffix,"")
        languageKeyMap[name]?.let {
            map[it] = listFile
        }
    }
    return map
    //德语 - de-rDE
    //法语 - fr-rFR
    //韩语 - ko-rKR
    //荷兰 - nl-rNL
    //马来语 - ms-rMY
    //葡萄牙 - pt-rPT
    //日语 - ja-rJP
    //泰语 - th-rTH
    //土耳其语 - tr-rTR
    //西班牙语 - es-rES
    //意大利语 - it-rIT
    //印尼语 - in-rID
    //英语 - en
    //越南语 - vi-rVN
//    "阿拉伯语" to "ar-rEG",
//    "俄罗斯语" to "ru-rRu",
    //中文繁体 - zh-rTW
    //中文简体 - zh-rCN
}

private val languageKeyMap = mapOf(
    "德语" to "de-rDE",
    "法语" to "fr-rFR",
    "韩语" to "ko-rKR",
    "荷兰语" to "nl-rNL",
    "马来语" to "ms-rMY",
    "葡萄牙语" to "pt-rPT",
    "日语" to "ja-rJP",
    "泰语" to "th-rTH",
    "土耳其语" to "tr-rTR",
    "西班牙语" to "es-rES",
    "意大利语" to "it-rIT",
    "印尼语" to "in-rID",
    "英文" to "en",
    "越南语" to "vi-rVN",
    "阿拉伯语" to "ar-rEG",
    "俄罗斯语" to "ru-rRU",
    "中文繁体" to "zh-rTW",
    "中文简体" to "zh-rCN",
)
