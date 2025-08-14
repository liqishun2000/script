package script.android.stringRes

import script.android.stringRes.common.LanguageInfo
import java.io.File

private const val translationFilePath = "E:\\work\\scanner\\1.2.0.0\\QR二维码翻译 V1.2.0.0\\QR二维码翻译 V1.2.0.0"
private const val targetProjectResFilePath = "E:\\tem\\res"

//替换string.xml中相同name的content
private fun main() {
    val languageFileMap = LanguageInfo.getLanguageFile(translationFilePath)

    val resFile = File(targetProjectResFilePath)

    LanguageInfo.mergeValuesFile(resFile)

    val valuesFiles = resFile.listFiles()?.filter { it.name.contains("values-") }

    valuesFiles?.forEach{ valuesFile->
        languageFileMap.toList().forEach { pair->
            if(valuesFile.name.contains(pair.first)){
                runCatching {
                    LanguageInfo.handleString(pair.second)
                }.onSuccess { needAddString->
                    val stringFile = valuesFile.listFiles()!!.first()
                    replaceInfo(stringFile,needAddString)
                }.onFailure {
                    throw Exception("file:${pair.second.absolutePath} msg:${it.message}")
                }
            }
        }

    }
}

private fun replaceInfo(file: File, newLines: List<String>) {
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
