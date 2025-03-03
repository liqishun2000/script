package script.android

import java.io.File

fun replaceResFileName(allFiles:ProjectBean,resPrefix:List<Pair<String,String>>) {

//    val colorMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.colorDirectory,resPrefix)
//    val layoutMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.layoutDirectory,resPrefix)
    val drawableMap:MutableMap<String,String> = getReplaceMap(allFiles.resFiles.drawableDirectory,resPrefix)

    replaceDrawableName(allFiles,drawableMap)
}

private fun replaceDrawableName(bean:ProjectBean,map:Map<String,String>){
    bean.javaFiles.forEach { path->
        val javaFile = File(path)
        val readLines = javaFile.readLines()
        val newLines = readLines.map { line->
            var newLine = line
            map.forEach{ pair->
                val origin = "R.drawable.${pair.key}"
                val target = "R.drawable.${pair.value}"
                if(line.contains(origin)){
                    newLine = line.replace(origin,target)
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
                    val origin = "@drawable/${pair.key}"
                    val target = "@drawable/${pair.value}"
                    if(line.contains(origin)){
                        newLine = line.replace(origin,target)
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