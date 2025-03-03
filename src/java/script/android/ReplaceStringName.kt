package script.android

import java.io.File

fun replaceStringName(allFiles:ProjectBean,stringPrefix:List<Pair<String,String>>) {
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

            stringPrefix.forEach { pair->
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

private fun replaceAllStringName(bean:ProjectBean,map:Map<String,String>){
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