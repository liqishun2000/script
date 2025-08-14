package script.android.stringRes

import script.android.stringRes.common.LanguageInfo
import java.io.File

private const val translationFilePath = "E:\\work\\scanner\\1.2.0.0\\QR二维码翻译 V1.2.0.0\\QR二维码翻译 V1.2.0.0"
private const val targetProjectResFilePath = "E:\\tem\\res"
private const val endFlag = "</resources>"

//翻译文本添加到文件中
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
                    insertLinesBeforeLastTag(stringFile,needAddString)
                }.onFailure {
                    throw Exception("file:${pair.second.absolutePath} msg:${it.message}")
                }
            }
        }

    }

}

private fun insertLinesBeforeLastTag(file: File, newLines: List<String>) {
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
