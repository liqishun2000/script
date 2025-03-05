package script.android

import java.io.File

fun replaceIdName(allFiles:ProjectBean,stringPrefix:List<Pair<String,String>>,bindingNames:List<String>) {
    println("replace id name...")

    val isAddPrefix = stringPrefix.size == 1 && stringPrefix.first().first == ""

    val map:MutableMap<String,String> = mutableMapOf()

    //id映射
    allFiles.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()
            readLines.forEach { line->
                val trimIndent = line.trimIndent()
                if(trimIndent.startsWith("android:id=\"@+id/")){
                    val id = extractIdFromString(trimIndent) ?: ""
                    if(id.isNotBlank() && id != "root"){
                        if(isAddPrefix){
                            val addPrefixId = addPrefix(id, stringPrefix.first().second)
                            map[id] = addPrefixId
                        }else{
                            stringPrefix.forEach { pair->
                                if(id.startsWith(pair.first)){
                                    val drop = id.drop(pair.first.length)
                                    val newName = pair.second+drop
                                    map[id] = newName
                                }
                            }
                        }

                    }
                }
            }

        }
    }

    //handle include
    var includeList:MutableList<String> = mutableListOf()

    allFiles.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()

            for (i in readLines.indices) {
                val line = readLines[i]
                val trimIndent = line.trimIndent()
                if(trimIndent.startsWith("android:id=\"@+id/")){
                    val id = extractIdFromString(trimIndent) ?: ""
                    if(id.isNotBlank() && id != "root"){
                        if(isInclude(readLines,i)){
                            val newId = map[id] ?: continue
                            val bindMap = includeList.associateBy { it }.toMutableMap()
                            bindMap[newId] = newId
                            includeList = bindMap.values.toMutableList()
                        }
                    }
                }
            }
        }
    }

    replaceAllIdName(allFiles,map,bindingNames,includeList)

    println("replace id name over")
}

private fun isInclude(lines:List<String>,index:Int):Boolean{
    var lastIndex = index - 1
    while (lastIndex in lines.indices) {
        val lastLine = lines[lastIndex].trimIndent()
        if (lastLine.startsWith("<")) {
            // 判断是否是include标签
            return lastLine.contains("include")
        }
        lastIndex--
    }
    return false
}

private fun replaceAllIdName(bean:ProjectBean,map:Map<String,String>,bindingNames:List<String>,includeList: List<String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val originId = "R.id.${pair.key}"
                val targetId = "R.id.${pair.value}"
                if (newLine.contains(originId)) {
                    newLine = newLine.replace(originId, targetId)
                }

                val bindingName = getBindingName(pair.key)
                bindingNames.forEach { binding->
                    val originBinding = "$binding.$bindingName"
                    val targetBinding = "$binding.${pair.value}"

                    if(newLine.contains(originBinding)){
                        newLine = newLine.replace(originBinding,targetBinding)
                    }
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val bindingName = getBindingName(pair.key)
                includeList.forEach { binding->
                    val originBinding = "$binding.$bindingName"
                    val targetBinding = "$binding.${pair.value}"

                    if(newLine.contains(originBinding)){
                        newLine = newLine.replace(originBinding,targetBinding)
                    }
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    bean.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                var newLine = line
                map.forEach{ pair->
                    val origin = "android:id=\"@+id/${pair.key}"
                    val target = "android:id=\"@+id/${pair.value}"
                    if(newLine.contains(origin)){
                        newLine = newLine.replace(origin,target)
                    }

                    val originRef = "=\"@id/${pair.key}"
                    val targetRef = "=\"@id/${pair.value}"
                    if(newLine.contains(originRef)){
                        newLine = newLine.replace(originRef,targetRef)
                    }

                    val originRefDef = "=\"@+id/${pair.key}"
                    val targetRefDef = "=\"@+id/${pair.value}"
                    if(newLine.contains(originRefDef)){
                        newLine = newLine.replace(originRefDef,targetRefDef)
                    }
                }
                newLine
            }
            file.writeText(newLines.joinToString("\r\n"))
        }
    }
}

private fun getBindingName(layoutId:String):String{
    return if ('_' in layoutId) {
        layoutId.split('_')
            .joinToString("") { part ->
                part.lowercase().replaceFirstChar { it.uppercase() }
            }.replaceFirstChar { it.lowercase() }
    } else {
        layoutId
    }
}

private fun addPrefix(original: String,prefix:String): String {
    val camelCase = if ('_' in original) {
        original.split('_')
            .joinToString("") { part ->
                part.lowercase().replaceFirstChar { it.uppercase() }
            }
    } else {
        original.replaceFirstChar { it.uppercase() }
    }
    return "$prefix$camelCase"
}

private fun extractIdFromString(input: String): String? {
    val pattern = Regex("@\\+id/(\\w+)")
    return pattern.find(input)?.groupValues?.get(1)
}