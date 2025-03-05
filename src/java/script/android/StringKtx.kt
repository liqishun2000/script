package script.android

import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

fun String.containsExactMatch(target: String): Boolean {
    // 转义目标字符串中的特殊字符（如 .、$ 等）
    val escapedTarget = Regex.escape(target)
    // 构建正则表达式，使用单词边界确保精确匹配
    val regex = Regex("\\b$escapedTarget\\b")
    // 检查是否存在匹配项
    return regex.containsMatchIn(this)
}

fun String.aesEncrypt(key: String): String {
    val keyBytes = key.toByteArray(charset("UTF-8"))
    val secretKey = SecretKeySpec(keyBytes, "AES")
    val iv = IvParameterSpec(secretKey.encoded)
    val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
    cipher.init(Cipher.ENCRYPT_MODE, secretKey,iv)
    val encryptedBytes = cipher.doFinal(this.toByteArray(Charsets.UTF_8))
    return Base64.getEncoder().encodeToString(encryptedBytes)
}

fun String.aesDecrypt(key: String): String {
    val keyBytes = key.toByteArray(charset("UTF-8"))
    val secretKey = SecretKeySpec(keyBytes, "AES")
    val iv = IvParameterSpec(secretKey.encoded)
    val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
    cipher.init(Cipher.DECRYPT_MODE, secretKey,iv)
    val decryptedBytes = cipher.doFinal(Base64.getDecoder().decode(this))
    return String(decryptedBytes, Charsets.UTF_8)
}


fun String.md5(): String {
    val md = MessageDigest.getInstance("MD5")
    val digest = md.digest(this.toByteArray(Charsets.UTF_8))
    return digest.fold("") { str, byte ->
        str + "%02x".format(byte)
    }
}
