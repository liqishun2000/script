package script.handlePicture

import java.awt.Graphics2D
import java.awt.geom.AffineTransform
import java.awt.image.BufferedImage
import java.io.File
import javax.imageio.ImageIO

private val IMAGE_EXTENSIONS = setOf("png", "jpg", "jpeg", "gif", "bmp", "webp")
private val parentFilePath = """E:\tem\图片"""

fun main(args: Array<String>) {
    val parentFile = File(parentFilePath)

    require(parentFile.isDirectory) { "不是有效目录: ${parentFile.absolutePath}" }

    val outputDir = File(parentFile.parentFile, "${parentFile.name}-output")
    outputDir.mkdirs()

    val files = parentFile.listFiles()
        ?.filter { it.isFile && it.extension.lowercase() in IMAGE_EXTENSIONS }
        .orEmpty()
        .sortedBy { it.name }

    if (files.isEmpty()) {
        println("未找到图片文件，目录: ${parentFile.absolutePath}")
        return
    }

    files.forEach { file ->
        val buffered = ImageIO.read(file)
        if (buffered == null) {
            println("跳过（无法解码）: ${file.name}")
            return@forEach
        }
        val mirrored = mirrorHorizontal(buffered)
        val format = imageWriteFormat(file.extension.lowercase())
        val outFile = File(outputDir, file.name)
        if (!ImageIO.write(mirrored, format, outFile)) {
            println("写入失败: ${outFile.name}，格式: $format")
        } else {
            println("已输出: ${outFile.absolutePath}")
        }
    }
}

private fun mirrorHorizontal(source: BufferedImage): BufferedImage {
    val w = source.width
    val h = source.height
    val type = if (source.type == BufferedImage.TYPE_CUSTOM || source.type == 0) {
        BufferedImage.TYPE_INT_ARGB
    } else {
        source.type
    }
    val dest = BufferedImage(w, h, type)
    val g2d = dest.createGraphics() as Graphics2D
    val tx = AffineTransform.getScaleInstance(-1.0, 1.0)
    tx.translate(-w.toDouble(), 0.0)
    g2d.transform(tx)
    g2d.drawImage(source, 0, 0, null)
    g2d.dispose()
    return dest
}

private fun imageWriteFormat(ext: String): String = when (ext) {
    "jpg", "jpeg" -> "jpeg"
    "png" -> "png"
    "gif" -> "gif"
    "bmp" -> "bmp"
    "webp" -> "webp"
    else -> "png"
}
