package script

import kotlin.random.Random

private fun main() {
    HybridPackageGenerator.generatePackages(3).forEach {
        println(it)
    }
}

object HybridPackageGenerator {
    // 原始词汇池的字母集合（去除重复）
    private val charPool = listOf(
        "abcdefghijklmnopqrstuvwxyz"
    ).flatMap { it.toList() } // 将所有单词拆解成单个字母
        .distinct()
        .shuffled()

    // 生成完全随机但符合自然语言特征的字符串
    private fun randomWord(min: Int = 5, max: Int = 8): String {
        val length = Random.nextInt(min, max + 1)
        return buildString {
            repeat(length) {
                append(charPool.random())
            }
        }.lowercase()
    }

    // 生成包名段落（3-5段）
    fun generatePackageName(): String {
        return List(Random.nextInt(3, 6)) {
            randomWord()
        }.joinToString(".")
    }

    // 批量生成
    fun generatePackages(count: Int): Set<String> {
        return mutableSetOf<String>().apply {
            while (size < count) add(generatePackageName())
        }
    }
}
