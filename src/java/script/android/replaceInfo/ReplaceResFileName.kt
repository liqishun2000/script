package script.android.replaceInfo

import java.io.File

/** 替换res目录下文件名称 */
fun replaceResFileName(allFiles: ProjectBean, resPrefix:List<Pair<String,String>>) {
    println("replace res file name...")

    val colorMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.colorDirectory,resPrefix)
    val layoutMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.layoutDirectory,resPrefix)
    val drawableMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.drawableDirectory,resPrefix)

    replaceColorName(allFiles,colorMap)
    replaceDrawableName(allFiles,drawableMap)
    replaceLayoutName(allFiles,layoutMap)

    println("replace res file over")
}

private fun replaceColorName(bean: ProjectBean, map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val origin = "R.color.${pair.key}"
                val target = "R.color.${pair.value}"
                if(newLine.contains(origin)){
                    newLine = newLine.replace(origin,target)
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    bean.resFiles.drawableDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            if(file.name.endsWith(".xml")){
                val readLines = file.readLines()
                val newLines = readLines.map { line->
                    var newLine = line
                    map.forEach{ pair->
                        val origin = "@color/${pair.key}"
                        val target = "@color/${pair.value}"
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

    bean.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                var newLine = line
                map.forEach{ pair->
                    val origin = "@color/${pair.key}"
                    val target = "@color/${pair.value}"
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

private fun replaceLayoutName(bean: ProjectBean, map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val binding = pair.key.convertToCamelCase() + "Binding"
                val targetBinding = pair.value.convertToCamelCase() + "Binding"
                if(newLine.containsExactMatch(binding)){
                    newLine = newLine.replace(binding,targetBinding)
                }

                val origin = "R.layout.${pair.key}"
                val target = "R.layout.${pair.value}"
                if(newLine.contains(origin)){
                    newLine = newLine.replace(origin,target)
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
                    val origin = "@layout/${pair.key}"
                    val target = "@layout/${pair.value}"
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

private fun String.convertToCamelCase(): String {
    return this.split('_')
        .filter { it.isNotEmpty() }
        .joinToString("") { it.replaceFirstChar { char -> char.uppercase() } }
}


private fun replaceDrawableName(bean: ProjectBean, map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val origin = "R.drawable.${pair.key}"
                val target = "R.drawable.${pair.value}"
                if(newLine.contains(origin)){
                    newLine = newLine.replace(origin,target)
                }
            }
            newLine
        }
        javaFile.writeText(newLines.joinToString("\r\n"))
    }

    handleResDrawable(bean.resFiles.layoutDirectory,map)
    handleResDrawable(bean.resFiles.valuesDirectory,map)

    bean.resFiles.drawableDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            if(file.name.endsWith(".xml")){
                val readLines = file.readLines()
                val newLines = readLines.map { line->
                    var newLine = line
                    map.forEach{ pair->
                        val origin = "@drawable/${pair.key}"
                        val target = "@drawable/${pair.value}"
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
}

private fun handleResDrawable(directory:List<String>,map:Map<String,String>){
    directory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readLines = file.readLines()
            val newLines = readLines.map { line->
                var newLine = line
                map.forEach{ pair->
                    val origin = "@drawable/${pair.key}"
                    val target = "@drawable/${pair.value}"
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

private fun getReplaceMap(list:List<String>,resPrefix: List<Pair<String, String>>):MutableMap<String,String>{
    val map:MutableMap<String,String> = mutableMapOf()
    list.forEach { path->
        File(path).listFiles()?.forEach { file->
            resPrefix.forEach { pair->
                if(file.name.startsWith(pair.first)){
                    val drop = file.name.drop(pair.first.length)
                    val newName = pair.second + drop
                    map[file.name.substringBeforeLast(".")] = newName.substringBeforeLast(".")
                    file.renameTo(File(file.parentFile.absolutePath+"\\\\$newName"))
                }
            }
        }
    }
    return map
}