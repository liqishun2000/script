package script.android.replaceInfo

import java.io.File
import kotlin.random.Random

private var colorNameList:List<String> = mutableListOf()
private var stringNameList:List<String> = mutableListOf()
private var drawableNameList:List<String> = mutableListOf()
private var pictureNameList:List<String> = mutableListOf()

fun insertUselessCompose(allFiles: ProjectBean){
    println("start insert useless widget..")

    colorNameList = getColorName(allFiles)
    stringNameList = getStringName(allFiles)
    drawableNameList = getDrawableName(allFiles)
    pictureNameList = getPictureName(allFiles)

    allFiles.resFiles.layoutDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            val readText = file.readText()
            var handleXml = removeEndEmptyLines(readText)
            handleXml = removeInnerEmptyLines(handleXml)
            handleXml = insertEmptyLines(handleXml)
            val handleText = insertTextToRandomEmptyLines(handleXml)
            file.writeText(handleText)
        }
    }

    println("insert useless widget over")
}


private fun getRandomTrue(percent:Int = 50):Boolean{
    return Random.nextInt(100)<percent
}

private fun getPictureName(allFiles: ProjectBean):List<String>{
    val list:MutableList<String> = mutableListOf()
    allFiles.resFiles.drawableDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            if(!file.name.endsWith(".xml")){
                list.add(file.name.substringBeforeLast("."))
            }
        }
    }
    return list
}

private fun getDrawableName(allFiles: ProjectBean):List<String>{
    val list:MutableList<String> = mutableListOf()
    allFiles.resFiles.drawableDirectory.forEach { path->
        File(path).listFiles()?.forEach { file->
            list.add(file.name.substringBeforeLast("."))
        }
    }
    return list
}

private fun getColorName(allFiles: ProjectBean):List<String>{
    val valuesDirectory = allFiles.resFiles.valuesDirectory.find { it.endsWith("values") }
        ?: throw Exception("can't find values directory")

    val colorFile = File(valuesDirectory).listFiles()?.find { it.name == "colors.xml" } ?:
    throw Exception("can't find colors.xml")

    val readLines = colorFile.readLines()
    val list:MutableList<String> = mutableListOf()
    readLines.forEach { line->
        val trimIndent = line.trimIndent()
        if(trimIndent.startsWith("<color")){
            val name = extractNameAttribute(trimIndent) ?: ""

            if(name.isNotBlank()){
                list.add(name)
            }
        }
    }
    return list
}

private fun getStringName(allFiles: ProjectBean):List<String>{
    val valuesDirectory = allFiles.resFiles.valuesDirectory.find { it.endsWith("values") }
        ?: throw Exception("can't find values directory")

    val stringFile = File(valuesDirectory).listFiles()?.find { it.name == "strings.xml" } ?:
    throw Exception("can't find strings.xml")

    val readLines = stringFile.readLines()
    val list:MutableList<String> = mutableListOf()
    readLines.forEach { line->
        val trimIndent = line.trimIndent()
        if(trimIndent.startsWith("<string")){
            val name = extractNameAttribute(trimIndent) ?: ""

            if(name.isNotBlank()){
                list.add(name)
            }
        }
    }
    return list
}


private fun extractNameAttribute(xmlString: String): String? {
    val pattern = Regex("""name=["']([^"']+)["']""")
    val matchResult = pattern.find(xmlString)
    return matchResult?.groupValues?.get(1)
}

private fun insertTextToRandomEmptyLines(xmlContent: String): String {
    val lines = xmlContent.split("\r\n").toMutableList()

    // 查找所有空行的索引
    val emptyLineIndices = lines.indices.filter { lines[it].trim().isEmpty() }

    if (emptyLineIndices.isEmpty()) return xmlContent

    val from = (emptyLineIndices.size * insertConfig.percent.first/100f).toInt()
    val end = (emptyLineIndices.size * insertConfig.percent.last/100f).toInt()

    val randomNum = if(from<end){
        Random.nextInt(from,end)
    }else{
        end
    }

    // 随机选择指定数量的空行（不超过实际空行数）
    val selectedIndices = emptyLineIndices.shuffled().take(
        randomNum
    ).sortedDescending()

    // 在选中的空行位置插入文本（保留原空行）
    var handleContent = xmlContent
    selectedIndices.forEach { index ->
        val findParentControl = findParentName(handleContent, index)

        if(findParentControl != null && canInsert(findParentControl)){
            val widget = if (getRandomTrue(insertConfig.createGroupProp)) {
                Widget.createGroup()
            }else{
                Widget.getRandomWidgetString()
            }
            val handleWidget = addInfoFromParent(findParentControl, widget)

            handleContent = insertWithIndent(handleContent,index,handleWidget)
        }
    }

    return handleContent
}

private fun addInfoFromParent(parent: String,list:List<String>):List<String>{
    val handleList:MutableList<String> = mutableListOf()
    handleList.addAll(list)
    if(parent.contains("androidx.constraintlayout.widget.ConstraintLayout")){
        handleList.addAll(1, listOf(
            "    app:layout_constraintTop_toTopOf=\"parent\"",
            "    app:layout_constraintStart_toStartOf=\"parent\"",
        ))
        if (getRandomTrue()) {
            handleList.addAll(1, listOf(
                "    app:layout_constraintEnd_toEndOf=\"parent\"",
            ))
        }
        if (getRandomTrue()) {
            handleList.addAll(1, listOf(
                "    app:layout_constraintBottom_toBottomOf=\"parent\"",
            ))
        }
    }
    return handleList
}

private fun canInsert(parent: String): Boolean {
    return when {
        parent.contains("ScrollView") -> false
        parent.contains("ViewFlipper") -> false
        else -> true
    }
}

private fun removeEndEmptyLines(xml:String):String{
    val lines = xml.split("\r\n").toMutableList()
    var emptyNum = 0
    for(i in lines.lastIndex downTo 0){
        if(lines[i].trim().isEmpty()){
            emptyNum++
        }else{
            break
        }
    }
    for (i in 0 until emptyNum) {
        lines.removeLast()
    }
    return lines.joinToString("\r\n")
}

private fun insertEmptyLines(xml: String): String {
    val lines = xml.split("\r\n")
    val result = mutableListOf<String>()
    var i = 0

    while (i < lines.size) {
        val currentLine = lines[i]
        result.add(currentLine)

        // 检测当前行是否是控件结束符
        if (isControlEnd(currentLine)) {
            // 检查后续非空行是否是控件开始
            var j = i + 1
            while (j < lines.size && lines[j].isBlank()) { j++ }

            // 满足插入条件：后续有控件开始，且中间没有空行
            if (j < lines.size && isControlStart(lines[j]) && j - i == 1) {
                result.add("")  // 在当前位置插入空行
            }
        }
        i++
    }
    return result.joinToString("\r\n")
}

// 判断是否是控件结束行（支持跨行标签）
private fun isControlEnd(line: String): Boolean {
    val trimmed = line.trim()
    return trimmed.endsWith("/>") ||
            (trimmed.endsWith(">") && !trimmed.endsWith("->") && !trimmed.endsWith("?>"))
}

// 判断是否是控件开始行（排除注释和声明）
private fun isControlStart(line: String): Boolean {
    val trimmed = line.trim()
    return trimmed.startsWith("<")
            && !trimmed.startsWith("</")
            && !trimmed.startsWith("<?")
            && !trimmed.startsWith("<!--")
}

private fun removeInnerEmptyLines(xml: String): String {
    val lines = xml.split("\r\n")
    val result = mutableListOf<String>()
    var inTag = false

    lines.forEach { line ->
        val trimmed = line.trim()
        when {
            // 检测到开始标签且未闭合
            trimmed.startsWith("<")
                    && !trimmed.startsWith("</")
                    && !trimmed.endsWith("/>")
                    && !trimmed.endsWith(">") -> {
                inTag = true
                result.add(line)
            }
            // 处于标签内部时跳过空行
            inTag && trimmed.isEmpty() -> Unit
            // 遇到闭合标签或结束标签
            inTag && (trimmed.endsWith("/>") || trimmed.startsWith("</")) -> {
                result.add(line)
                inTag = false
            }
            // 普通行处理
            else -> result.add(line)
        }
    }
    return result.joinToString("\r\n")
}

private fun findParentName(xmlContent: String, insertLineNumber: Int): String? {
    val lines = xmlContent.split("\r\n")
    val tagStack = ArrayDeque<String>()
    var currentLine = 0

    while (currentLine < lines.size) {
        if (currentLine == insertLineNumber) {
            return tagStack.lastOrNull()
        }

        val line = lines[currentLine].trim()
        when {
            line.startsWith("</") || line.contains("/>") -> { // 结束标签
                if (tagStack.isNotEmpty()) {
                    tagStack.removeLast()
                }
                currentLine++
            }
            line.startsWith("<") && !line.startsWith("<?") && !line.startsWith("<!--") -> { // 开始标签
                val tagName = parseTagName(line)
                if (!isSelfClosing(line)) {
                    tagStack.addLast(tagName)
                }
                currentLine++
            }
            else -> currentLine++
        }
    }
    return null
}



private fun parseTagName(line: String): String {
    val trimmed = line.substring(1).trimStart()
    val endIndex = trimmed.indexOfFirst { it == ' ' || it == '>' || it == '/' }
    return if (endIndex != -1) trimmed.substring(0, endIndex) else trimmed
}

private fun isSelfClosing(line: String): Boolean {
    return line.endsWith("/>")
}

private fun insertWithIndent(xmlContent: String, insertLine: Int, content: List<String>): String {
    val parent = findParentName(xmlContent, insertLine)
    val lines = xmlContent.split("\r\n").toMutableList()

    // 自动计算缩进
    val baseIndent = lines.getOrNull(insertLine)?.takeWhile { it == ' ' }?.length ?: 0
    val indent = if (parent != null) baseIndent + 4 else baseIndent

    // 插入带缩进的内容
    val handleContentList = content.map { data->
        " ".repeat(indent) + data
    }.toMutableList()

    handleContentList.add(0," ".repeat(indent)+"<!--region 无用控件-->")
    handleContentList.add(" ".repeat(indent)+"<!--endregion-->")

    lines.addAll(insertLine, handleContentList)

    return lines.joinToString("\r\n")
}

data class InsertConfig(
    val percent:IntRange,
    val maxLevel:Int,
    val maxChildNum:Int,
    val createGroupProp:Int,
)

private enum class Widget{
    TextView{
        override fun getStart() = "<TextView"
        override fun getPrivateAttribute(): List<String> {
            val list:MutableList<String> = mutableListOf()
            if(getRandomTrue(80)){
                val stringName = stringNameList.shuffled().first()
                list.add("    android:text=\"@string/${stringName}\"")
                val size = Random.nextInt(10,30)
                list.add("    android:textSize=\"${size}sp\"")
                if (getRandomTrue(70)) {
                    val colorName = colorNameList.shuffled().first()
                    list.add("    android:textColor=\"@color/${colorName}\"")
                }
                if(getRandomTrue()){
                    if (getRandomTrue()) {
                        list.add("    android:textStyle=\"bold\"")
                    }else{
                        list.add("    android:textStyle=\"italic\"")
                    }
                }

            }

            return list
        }
    },
    ImageView{
        val scaleTypeList = listOf(
            "center",
            "centerCrop",
            "centerInside",
            "fitXY",
            "fitCenter",
            "fitEnd",
            "fitStart",
            "matrix",
        )

        override fun getStart() = "<ImageView"
        override fun getPrivateAttribute(): List<String> {
            val list:MutableList<String> = mutableListOf()
            if(getRandomTrue(90)){
                val pictureName = pictureNameList.shuffled().first()
                list.add("    android:src=\"@drawable/${pictureName}\"")
                if (getRandomTrue(70)) {
                    val type = scaleTypeList.shuffled().first()
                    list.add("    android:scaleType=\"${type}\"")
                }
                if (getRandomTrue()) {
                    list.add("    android:adjustViewBounds=\"true\"")
                }

            }

            return list
        }
    },
    Button{
        override fun getStart() = "<Button"
    },
    FrameLayout{
        override fun getStart() = "<FrameLayout"
        override fun isViewGroup() = true
        override fun getViewGroupEnd() = "</FrameLayout>"
    },
    LinearLayout{
        override fun getStart() = "<LinearLayout"
        override fun isViewGroup() = true
        override fun getViewGroupEnd() = "</LinearLayout>"
        override fun getPrivateAttribute(): List<String> {
            val list:MutableList<String> = mutableListOf()
            if (getRandomTrue()) {
                list.add("    android:orientation=\"horizontal\"")
            }else{
                list.add("    android:orientation=\"vertical\"")
            }

            return list
        }
    },
    RelativeLayout{
        override fun getStart() = "<RelativeLayout"
        override fun isViewGroup() = true
        override fun getViewGroupEnd() = "</RelativeLayout>"
    }
    ;
    open fun getStart():String = ""
    open fun isViewGroup():Boolean = false
    open fun getViewGroupEnd():String = ""
    open fun getPrivateAttribute():List<String> = listOf()

    fun createWidget():List<String>{
        val list:MutableList<String> = mutableListOf()
        list.add(getStart())
        list.addAll(getCommonAttribute())
        list.addAll(getPrivateAttribute())
        list.add(getEnd())
        return list
    }
    fun getCommonAttribute() :List<String>{
        val list:MutableList<String> = mutableListOf()
        if(getRandomTrue(70)){
            //是否添加visibility
            if(getRandomTrue()){
                //visibility的属性是否为gone
                list.add("    android:visibility=\"gone\"")
                var zero = getRandomTrue()
                var size = Random.nextInt(30)
                if(zero){
                    list.add("    android:layout_width=\"${size}dp\"")
                }else{
                    list.add("    android:layout_width=\"wrap_content\"")
                }
                zero = getRandomTrue()
                size = Random.nextInt(30)
                if(zero){
                    list.add("    android:layout_height=\"${size}dp\"")
                }else{
                    list.add("    android:layout_height=\"wrap_content\"")
                }
            }else{
                list.add("    android:visibility=\"invisible\"")
                list.add("    android:layout_width=\"0dp\"")
                list.add("    android:layout_height=\"0dp\"")
            }

        }else{
            //不添加visibility
            list.add("    android:layout_width=\"0dp\"")
            list.add("    android:layout_height=\"0dp\"")
        }

        //是否添加background
        if (getRandomTrue(70)) {
            //是否添加bg
            if(getRandomTrue()){
                //是否是color
                val colorName = colorNameList.shuffled().first()
                list.add("    android:background=\"@color/$colorName\"")
            }else{
                val drawableName = drawableNameList.shuffled().first()
                list.add("    android:background=\"@drawable/$drawableName\"")
            }
        }

        //添加gravity
        if(getRandomTrue()){
            val gravityName = gravityType.shuffled().first()
            list.add("    android:gravity=\"${gravityName}\"")
        }

        return list
    }
    fun getEnd():String = "    />"





    companion object{
        val gravityType = listOf(
            "top",
            "bottom",
            "left",
            "right",
            "center_vertical",
            "center_horizontal",
            "fill_horizontal",
            "center",
            "fill",
            "clip_vertical",
            "clip_horizontal",
            "start",
            "end",
        )

        fun getRandomWidgetString():List<String>{
            return Widget.entries.shuffled().first().createWidget()
        }

        fun getRandomViewString():List<String>{
            return Widget.entries.filter { !it.isViewGroup() }.shuffled().first().createWidget()
        }


        fun getRandomViewGroup() = Widget.entries.filter { it.isViewGroup() }.shuffled().first()

        fun createGroup(level:Int = 0):List<String>{
            var isViewGroup = false
            if (getRandomTrue(insertConfig.maxLevel*30 - level*30)) {
                isViewGroup = true
            }
            if(level == 0){
                isViewGroup = true
            }
            val list:MutableList<String> = mutableListOf()
            val empty = level*4

            if(isViewGroup){
                //父容器
                val randomViewGroup = Widget.getRandomViewGroup()
                list.add(" ".repeat(empty)+randomViewGroup.getStart())
                randomViewGroup.getCommonAttribute().forEach {
                    list.add(" ".repeat(empty)+it)
                }
                randomViewGroup.getPrivateAttribute().forEach {
                    list.add(" ".repeat(empty)+it)
                }
                list.add(" ".repeat(empty+4)+">")
                list.add(" ".repeat(empty))

                val nextInt = Random.nextInt(1,insertConfig.maxChildNum)
                for (i in 0 until nextInt) {
                    list.addAll(createGroup(level+1))
                }

                list.add(" ".repeat(empty)+randomViewGroup.getViewGroupEnd())
            }else{
                getRandomViewString().forEach {
                    list.add(" ".repeat(empty)+it)
                }

                list.add(" ".repeat(empty))
            }

            return list
        }

    }
}
