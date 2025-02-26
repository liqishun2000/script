package script

import java.io.File

const val translationFilePath = "E:\\work\\scanner\\1.1.0.0\\QR二维码翻译 V1.1.0.0\\QR二维码翻译 V1.1.0.0"
const val targetProjectResFilePath = "E:\\code\\first\\app\\src\\main\\res"
const val endFlag = "</resources>"

//翻译文本添加到文件中
fun main() {
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
                    "    $string" // 添加缩进
                }
                val stringFile = valuesFile.listFiles()!!.first()
                insertLinesBeforeLastTag(stringFile,needAddString)
            }
        }

    }

}

fun insertLinesBeforeLastTag(file: File, newLines: List<String>) {
    val lines = file.readLines().toMutableList()

    when {
        lines.last().contains(endFlag) -> {
            // 在结尾标识前批量插入多行
            lines.addAll(lines.lastIndex, newLines)
        }
        else -> {
            // 无结尾标识时在文件末尾插入
            lines.addAll(newLines)
        }
    }

    // 保持原文件换行格式
    file.writeText(lines.joinToString("\n"))
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
    "中文繁体" to "zh-rTW",
    "中文简体" to "zh-rCN",
)
