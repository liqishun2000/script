package script.android.stringRes.common

import java.io.File

class ContentException(msg:String = ""):Exception(msg)

object LanguageInfo {

    private const val END_FLAG = "</resources>"
    private const val TARGET_FILE_NAME = "strings.xml"

    fun mergeValuesFile(resFile:File){
        val valuesFiles = resFile.listFiles()?.filter { it.name.contains("values-") && !it.name.contains("night") }

        if (valuesFiles == null) {
            throw Exception("there is no values- file")
        }
        for(i in valuesFiles.indices){
            val valueFile = valuesFiles[i]

            var childFiles = valueFile.listFiles()

            if(childFiles.isNullOrEmpty()){
                println("${valueFile.absolutePath} has no child")
                continue
            }

            var hasTargetFile = false
            childFiles.find { it.name == TARGET_FILE_NAME }?.let {
                hasTargetFile = true
            }

            if(hasTargetFile && childFiles.size == 1){
                continue
            }

            if(!hasTargetFile){
                val file = File("${valueFile.absolutePath}\\$TARGET_FILE_NAME")
                file.createNewFile()
                val origin = """
                <?xml version="1.0" encoding="UTF-8"?><resources>
                </resources>
            """.trimIndent()
                file.writeText(origin)
            }

            childFiles = valueFile.listFiles()!!
            val singleFile = childFiles.find { it.name == TARGET_FILE_NAME }!!

            childFiles.forEach { file->
                if(file.name != TARGET_FILE_NAME){
                    val lines = file.readLines().filter { it.contains("<string") && it.contains("</string>") }
                    insertLinesBeforeLastTag(singleFile,lines)
                    file.delete()
                }
            }
        }
    }

    private fun insertLinesBeforeLastTag(file: File, newLines: List<String>) {
        val lines = file.readLines().toMutableList()

        when {
            lines.last().contains(END_FLAG) -> {
                // 在结尾标识前批量插入多行
                lines.addAll(lines.lastIndex, newLines)
            }
        }

        // 保持原文件换行格式
        file.writeText(lines.joinToString("\n"))
    }

    fun handleString(file:File):List<String>{
        return file.bufferedReader(Charsets.UTF_8).use { reader ->
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
            //格式化
            handleString = formatString(handleString)

            "    $handleString"
        }
    }

    private fun formatString(input: String):String{
        var formatString = "<string name=\"%s\">%s</string>"
        val regex = Regex("""<string (.*)="(.*)">(.*)</string>""")
        regex.find(input)?.groups?.let {
            val name = it[2]?.value
            val content = it[3]?.value
            formatString = formatString.format(name,content)
        } ?: throw ContentException("文件内容格式异常:$input")
        return formatString
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

    fun getLanguageFile(path:String):Map<String, File>{
        val origin = File(path)

        val map:MutableMap<String, File> = mutableMapOf()
        origin.listFiles()?.forEach { listFile ->
            val suffix = listFile.name.substring(listFile.name.lastIndexOf("."))
            val name = listFile.name.replace(suffix, "")
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
        "阿拉伯语" to "ar-rEG",
        "爱尔兰语" to "ga-rIE",
        "丹麦语" to "da-rDK",
        "德语" to "de-rDE",
        "俄语" to "ru-rRU",
        "法语" to "fr-rFR",
        "芬兰语" to "fi-rFI",
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
        "中文繁体" to "zh-rTW",
        "中文简体" to "zh-rCN",
    )
}