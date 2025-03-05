package script.android.replaceInfo

import java.io.File

fun replaceStringName(allFiles: ProjectBean, stringPrefix:List<Pair<String,String>>) {
    println("replace string name...")

    val valuesDirectory = allFiles.resFiles.valuesDirectory.find { it.endsWith("values") }
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

    println("replace string name over")
}

private fun replaceAllStringName(bean: ProjectBean, map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val origin = "R.string.${pair.key}"
                val target = "R.string.${pair.value}"
                if(newLine.contains(origin)){
                    newLine = newLine.replace(origin,target)
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    bean.resFiles.valuesDirectory.forEach { path->
        File(path).listFiles()?.find { it.name == "strings.xml" }?.let { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                var newLine = line
                map.forEach{ pair->
                    val origin = "name=\"${pair.key}"
                    val target = "name=\"${pair.value}"
                    if(newLine.contains(origin)){
                        newLine = newLine.replace(origin,target)
                    }
                }
                newLine
            }
            file.writeText(newLines.joinToString("\r\n"))
        }
    }

    bean.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                var newLine = line
                map.forEach{ pair->
                    val origin = "@string/${pair.key}"
                    val target = "@string/${pair.value}"
                    if(newLine.contains(origin)){
                        newLine = newLine.replace(origin,target)
                    }
                }
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