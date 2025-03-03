package script.android

import java.io.File

data class ProjectBean(
    val javaFiles: List<String>,
    val resFiles: ResourceFiles,
)

data class ResourceFiles(
    val valuesFiles: List<String> = listOf(),
    val layoutFiles: List<String> = listOf(),
    val pictureFiles: List<String> = listOf(),
    val colorFiles: List<String> = listOf(),
    val drawableFiles: List<String> = listOf(),
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
    val layoutFiles: MutableList<String> = mutableListOf()
    val valuesFiles: MutableList<String> = mutableListOf()
    file.listFiles()?.forEach {
        when {
            it.name == "layout" -> {
                layoutFiles.add(it.absolutePath)
            }

            it.name.contains("values") -> {
                valuesFiles.add(it.absolutePath)
            }
        }
    }
    return ResourceFiles(
        layoutFiles = layoutFiles,
        valuesFiles = valuesFiles
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


