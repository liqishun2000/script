package script.android

import java.io.File

data class ProjectBean(
    val javaFiles: List<String>,
    val resFiles: ResourceFiles,
)

data class ResourceFiles(
    val colorDirectory: List<String> = listOf(),
    val drawableDirectory: List<String> = listOf(),
    val layoutDirectory: List<String> = listOf(),
    val valuesDirectory: List<String> = listOf(),
)

fun getAllFiles(mainPath: String): ProjectBean {
    var javaFiles: List<String> = mutableListOf()
    var resourceFile = ResourceFiles()

    File(mainPath).listFiles()?.forEach {
        when (it.name) {
            "java" -> {
                javaFiles = handleJavaFiles(it)
            }

            "res" -> {
                resourceFile = handleResFiles(it)
            }
        }
    }

    return ProjectBean(
        javaFiles = javaFiles,
        resFiles = resourceFile,
    )
}

private fun handleResFiles(file: File): ResourceFiles {
    val layoutDirectory: MutableList<String> = mutableListOf()
    val valuesDirectory: MutableList<String> = mutableListOf()
    val colorDirectory:MutableList<String> = mutableListOf()
    val drawableDirectory:MutableList<String> = mutableListOf()
    file.listFiles()?.forEach {
        when {
            it.name == "layout" -> {
                layoutDirectory.add(it.absolutePath)
            }

            it.name.contains("values") -> {
                valuesDirectory.add(it.absolutePath)
            }
            it.name == "color"->{
                colorDirectory.add(it.absolutePath)
            }
            it.name.contains("drawable")->{
                drawableDirectory.add(it.absolutePath)
            }
        }
    }
    return ResourceFiles(
        layoutDirectory = layoutDirectory,
        valuesDirectory = valuesDirectory,
        colorDirectory = colorDirectory,
        drawableDirectory = drawableDirectory,
    )
}

private fun handleJavaFiles(file: File): List<String> {
    return traversalJavaFiles(file)
}

private fun traversalJavaFiles(file: File): MutableList<String> {
    if (file.isFile) {
        return mutableListOf(file.absolutePath)
    }

    val fileList: MutableList<String> = mutableListOf()

    if (file.isDirectory) {
        file.listFiles()?.forEach {
            val childFiles = traversalJavaFiles(it)
            fileList.addAll(childFiles)
        }
    }
    return fileList
}


