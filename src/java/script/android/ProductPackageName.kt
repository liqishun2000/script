package script.android

import kotlin.random.Random

fun main() {
    val packageNames = generatePackageNames()
    packageNames.forEach { println(it) }
}

private fun generatePackageNames() = (1..3).map { buildRandomPackageName() }.distinct()

private fun buildRandomPackageName(): String {
    val structure = when (Random.nextInt(5)) {
        0 -> "${randomTLD()}.${randomCompany()}"
        1 -> "${randomTLD()}.${randomCompany()}.${randomProject()}"
        2 -> "${randomTLD()}.${randomAdjective()}${randomNoun()}"
        3 -> "${randomTLD()}.${randomCode(3)}.${randomProject()}"
        else -> "${randomTLD()}.${randomProject()}${randomCode(4)}"
    }
    return structure.lowercase()
}

// 扩展词汇库
private val tlds = listOf("com", "org", "net", "io", "co", "dev", "ai", "tech", "labs", "studio")
private val companies = listOf("nexus", "quantum", "zenith", "phoenix", "vortex", "orbit", "nimbus", "astra", "echo", "pixel")
private val projects = listOf("platform", "engine", "system", "core", "hub", "matrix", "pulse", "forge", "spark", "nexa")
private val adjectives = listOf("alpha", "hyper", "quantum", "neon", "zen", "flux", "nova", "stellar", "fusion", "crypto")
private val nouns = listOf("wave", "node", "grid", "sphere", "drift", "shift", "byte", "bit", "chain", "sync")

// 随机生成器
private fun randomTLD() = tlds.random()
private fun randomCompany() = companies.random()
private fun randomProject() = projects.random()
private fun randomAdjective() = adjectives.random()
private fun randomNoun() = nouns.random()
private fun randomCode(length: Int) = buildString {
    repeat(length) {
        append(if (Random.nextBoolean()) ('a'..'z').random() else ('0'..'9').random())
    }
}