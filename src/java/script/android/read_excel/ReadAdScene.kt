package script.android.read_excel

private const val excel = """序号	广告场景	广告类型	预加载/请求	失败	服务端配置	
1	开屏	开屏插页	启动APP即开始请求广告信息（开屏loading界面）。	loading时长最多10秒。在10秒如请求失败则重试，重试请求次数最多1次，超过10秒不再重试直接进入APP。		
2	后台回切
（共用开屏广告位）	开屏/插页	展示规则同上。
回切应用后，如用户正在展示广告，则不再展示回切广告。	后台回切loading最长时长10秒，在此期间最多重试请求1次，超过10秒不再重试直接进入APP进入操作后台化的最后功能界面。	回切广告去除间隔5秒的判断	
2	解锁屏幕
（共用开屏广告位）	开屏/插页	在APP界面锁屏后，解锁应用时触发，展示规则同上。	loading最长时长10秒，在此期间最多重试请求1次，超过10秒不再重试直接进入APP进入操作后台化的最后功能界面。	去除 合并为2	
4	通知栏消息
（共用开屏广告位）	开屏/插页	启动APP即开始请求广告信息（开屏loading界面）	loading最长时长10秒，在此期间最多重试请求1次，超过10秒不再重试直接进入APP进入对应的功能页面		
5	常驻通知栏
（共用开屏广告位）	开屏/插页	同上	同上		
6	语言选择页底部	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	v1.2.0.2
7	首页底部banner	banner	进入首页开始请求，每次从其他页面返回至首页后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	v1.2.0.2
8	首页条形码入口下发	原生	进入首页开始请求，每次从其他页面返回至首页后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
9	扫描页底部banner	banner	进入扫描界面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	v1.2.0.2
10	扫描点击左上角关闭或点击物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	V1.2.0.3
1. 用户本次进入扫描页且扫描成功进入结果页，且展示过33、34场景从结果页返回至扫描页，点击左上角关闭或点击物理回退，不展示该广告。
2. 用户本次进入扫描页，没有扫描成功（没展示33、34）直接点击点击左上角关闭或点击物理回退则展示插页广告。
3. 未归因为广告用户，则无论什么情况，每次点击都触发插页广告。	
11	扫描结果页	原生	进入扫描结果页后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
12	扫描结果点击左上角返回或点击物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
13	Records页面scanning标签下第一条下方以及之后每间隔3条显示一个原生广告	原生	进入页面后开始请求（切换顶部tab标签重新进入标签页后重新请求）	10秒内重试1次，超过10秒后，不再展示该广告		
14	Records页面creat标签下第一条下方以及之后每间隔3条显示一个原生广告	原生	进入页面后开始请求（切换顶部tab标签重新进入标签页后重新请求）	10秒内重试1次，超过10秒后，不再展示该广告		
15	Records页面favorites标签下第一条下方以及之后每间隔3条显示一个原生广告	原生	进入页面后开始请求（切换顶部tab标签重新进入标签页后重新请求）	10秒内重试1次，超过10秒后，不再展示该广告		
16	Records页面无数据时默认页面“scan”按钮下方	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
17	Records缺省页，按钮下方	原生	切换顶部标签重新请求	10秒内重试1次，超过10秒后，不再展示该广告		
18	我的页面底部	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
19	退出应用弹窗下方	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
20	创建二维码剪切版下方	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
21	创建二维码输入弹窗下方	banner	打开弹窗后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
22	点击创建二维码	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告		
23	创建二维码结果页（二维码下方）	原生	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告		
24	创建二维码结果页点击返回或点击物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
25	首次启动APP语言选择页，点击next	插页	进入语言选择页后开始请求，关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	v1.2.0.2
26	编辑二维码样式页面底部	banner	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本	1
27	编辑二维码样式页面点击save按钮	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本	1
28	首次启动APP功能介绍页底部	原生广告	进入页面后开始请求，切换介绍页重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	v1.2.0.2
29	首次启动APP功能介绍页最后一页点击start	插页	1.进入语言选择页开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本
归因为广告用户后才展示该广告	1
30	records页面扫描记录结果页点击返回或物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本
归因为广告用户后才展示该广告	1
31	records页面创建记录结果页点击返回或物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本
归因为广告用户后才展示该广告	1
32	records页面收藏结果页点击返回或物理回退	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.0版本
归因为广告用户后才展示该广告	1
33	相机扫描成功	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.3版本
归因为广告用户后才展示该广告	
34	相册扫描成功（点击scan按钮）	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	1.2.0.3版本
归因为广告用户后才展示该广告	
V1.3.0.0						
35	文档扫描结果页点击exit，左上角返回，物理返回键	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
36	文档扫描结果页底部banner	banner	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
37	名片列表页模板第一行下方	原生	进入页面后开始请求
切换顶部tab重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
38	模板预览页下方	banner	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
39	模板预览页点击左上角关闭或物理回退键	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
40	名片生成结果页底部	banner	进入页面后开始请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
41	名片生成结果页点击返回或物理回退键	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	
42	名片列表页点击返回或物理回退键	插页	1.进入首页后开始请求
2.关闭广告后重新请求	10秒内重试1次，超过10秒后，不再展示该广告	归因为广告用户后才展示该广告	"""

private fun main() {
    val trimIndent = excel.trimIndent()
    val regex = Regex("""\n(\d+)\t""")
    val infos = regex.split(trimIndent)
    regex.findAll(trimIndent).forEachIndexed { index,result->
        val id = result.groupValues[1]
        val info = infos[index+1].split("\t").toMutableList().apply { add(0,id) }
        println(createOutput(info))
    }
}

private fun createOutput(units:List<String>):String{
    val id = units[0]
    val sceneName = units[1].replace("\n"," ")
    val type = units[2].replace("\n"," ")
    val request = units[3].replace("\n"," ")
    val fail = units[4].replace("\n"," ")
    val serverConfig = units[5].replace("\n"," ")
    val idName = "_$id"

    return """
     /**
     *  $type
     *  $sceneName
     *  $request
     *  $serverConfig
     * */
    const val $idName = "$id"
    """.trimIndent().split("\n").joinToString("\n") { "    $it" }
}

//private fun replaceId(id:String):String{
//    val idName = StringBuilder()
//    for (c in id) {
//        val newChar = when(c){
//            '1'-> 'y'
//            '2'-> 'e'
//            '3'-> 'x'
//            '4'-> 's'
//            '5'-> 'w'
//            '6'-> 'z'
//            '7'-> 'q'
//            '8'-> 'b'
//            '9'-> 'j'
//            '0'-> 'l'
//            else->'a'
//        }
//        idName.append(newChar)
//    }
//    return idName.toString()
//}