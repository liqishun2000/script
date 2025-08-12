package script.android.replaceInfo

import java.io.File

/** 替换Id名称 */
fun replaceIdNameV2(allFiles: ProjectBean, stringPrefix:List<Pair<String,String>>) {
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
                                    val handleId = getBindingName(id)
                                    val drop = handleId.drop(pair.first.replace("_","").length)
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


    replaceAllIdName(allFiles,map)

    println("replace id name over")
}

private fun replaceAllIdName(bean: ProjectBean, map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            if(!line.startsWith("import") && !line.startsWith("package")){
                map.forEach{ pair->
                    val originId = "R.id.${pair.key}"
                    val targetId = "R.id.${pair.value}"
                    if (newLine.contains(originId)) {
                        newLine = newLine.replace(originId, targetId)
                    }

                    val bindingName = getBindingName(pair.key)
                    val newName = pair.value
                    val regex = Regex("\\b${Regex.escape(bindingName)}\\b")
                    newLine = newLine.replace(regex,newName)
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
                part.replaceFirstChar { it.uppercase() }
            }.replaceFirstChar { it.lowercase() }
    } else {
        layoutId
    }
}

private fun addPrefix(original: String,prefix:String): String {
    val camelCase = if ('_' in original) {
        original.split('_')
            .joinToString("") { part ->
                part.replaceFirstChar { it.uppercase() }
            }
    } else {
        original.replaceFirstChar { it.uppercase() }
    }
    if(camelCase.startsWith(prefix,true)){
        return camelCase.replaceFirstChar { it.lowercase() }
    }
    return "$prefix$camelCase"
}

private fun extractIdFromString(input: String): String? {
    val pattern = Regex("@\\+id/(\\w+)")
    return pattern.find(input)?.groupValues?.get(1)
}