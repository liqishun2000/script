package script.android

import java.io.File

private const val targetProject: String = "E:\\code\\first\\app\\src\\main"
private val prefix = listOf(
    "t_" to "new_",
    "text_" to "new_",
)
/**
 *
 * v1.0.0.1
 * */
fun main() {
    val allFiles = getAllFiles(targetProject)

    val valuesDirectory = allFiles.resFiles.valuesFiles.find { it.endsWith("values") }
        ?: throw Exception("can't find values directory")

    val stringFile = File(valuesDirectory).listFiles()?.find { it.name == "strings.xml" } ?:
    throw Exception("can't find strings.xml")

    val readLines = stringFile.readLines()
    val map:MutableMap<String,String> = mutableMapOf()
    readLines.forEach { line->
        val trimIndent = line.trimIndent()
        if(trimIndent.startsWith("<string")){
            val name = extractNameAttribute(trimIndent) ?: ""

            prefix.forEach { pair->
                if(name.startsWith(pair.first)){
                    val drop = name.drop(pair.first.length)
                    val newName = pair.second+drop
                    map[name] = newName
                }
            }
        }
    }

    replaceAllStringName(allFiles,map)

}

fun replaceAllStringName(bean:ProjectBean,map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val origin = "R.string.${pair.key}"
                val target = "R.string.${pair.value}"
                if(line.contains(origin)){
                    newLine = line.replace(origin,target)
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    bean.resFiles.valuesFiles.forEach { path->
        File(path).listFiles()?.find { it.name == "strings.xml" }?.let { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                println(line)
                var newLine = line
                map.forEach{ pair->
                    val origin = "name=\"${pair.key}"
                    val target = "name=\"${pair.value}"
                    if(line.contains(origin)){
                        newLine = line.replace(origin,target)
                    }
                }
                println(newLine)
                newLine
            }
            file.writeText(newLines.joinToString("\r\n"))
        }
    }

}

private fun extractNameAttribute(xmlString: String): String? {
    val pattern = Regex("""name=["']([^"']+)["']""")
    val matchResult = pattern.find(xmlString)
    return matchResult?.groupValues?.get(1)
}