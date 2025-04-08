package script.android.read_excel

import script.android.replaceInfo.replaceIdName

private const val excel = """
    模块	事件ID	打点名称	参数	说明	备注	
开屏	Mobi_100101	展示开屏动画				1
	Mobi_100103	开屏动画loading结束				1
	Mobi_100104	首次启动APP_进入首页		首次安装并启动上报1次		1
	Mobi_100105	开屏广告请求到成功时长	time	秒		无
	Mobi_100106	开屏广告请求超时或报错无填充无法展示后进入首页				无
	Mobi_100107	从应用外召回开屏动画loading结束	type	1. 常驻通知栏 2.FCM 3.广播触发通知栏		1
	Mobi_100108	当日首次安装并启动APP并进入首页且次日启动
APP并进入首页				1
	Mobi_100109	APP首页从任何地方进入首页				1
通知栏	Mobi_100201	首页通知栏引导弹窗展示				
	Mobi_100202	首页通知栏引导弹窗_现在开启按钮				
	Mobi_100203	通知栏授权开启成功		每天只上报1次	1.首次开启成功后上报
2.每次启动APP上报，每天只上报一次	
	Mobi_100204	FCM通知栏接收到消息	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成	服务端下发编号：
123：二维码扫描   129：条形码扫描  125：扫码历史记录 124：创建二维码 135：编辑二维码 ？：文件扫描  ？：名片生成	
	Mobi_100205	FCM通知栏展示	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成	服务端下发编号：
123：二维码扫描   129：条形码扫描  125：扫码历史记录 124：创建二维码 135：编辑二维码 ？：文件扫描  ？：名片生成	
	Mobi_100206	FCM通知栏点击	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成	服务端下发编号：
123：二维码扫描   129：条形码扫描  125：扫码历史记录 124：创建二维码 135：编辑二维码 ？：文件扫描  ？：名片生成	
	Mobi_100207	FCM上报最新的token				
	Mobi_100410	接收到FCM推送消息的时候打点	messageId  推送消息id
type 跳转类型（1到10）
sid （预留备用）	服务端报表使用		
	Mobi_100208	本地广播触发通知栏触发	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成		
			scene	参见通知栏表格场景ID		
			touch	1.解锁屏幕 2.home 3.电源接口拔插 4.切换至后台 5.home其他情况		1
			TriggerType	1. 广播触发 2.轮询触发		1
	Mobi_100209	本地广播触发通知栏展示	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成		1
			scene	参见通知栏表格场景ID		1
			touch	1.解锁屏幕 2.home 3.电源接口拔插 4.切换至后台 5.home其他情况		1
			showCardType	1.大卡片 2 小卡片 展示是不懂大小卡片的		1
			TriggerType	1. 广播触发 2.轮询触发		1
	Mobi_100210	本地广播触发通知栏点击	type	1. 二维码扫描 2.条形码扫描 3.扫码历史记录 4.创建二维码  5.编辑二维码 6. 文件扫描 7. 名片生成		1
			scene	参见通知栏表格场景ID		1
			touch	1.解锁屏幕 2.home 3.电源接口拔插 4.切换至后台 5.home其他情况		1
			showCardType	1.大卡片 2 小卡片		1
			TriggerType	1. 广播触发 2.轮询触发		1
	Mobi_100211	本地通知间隔时间小于后台配置，展示失败				1
	Mobi_100212	挂起前台服务报错				1
	Mobi_100213	常驻通知栏展示				1
	Mobi_100214	常驻通知栏点击	type	1.创建二维码 2. 扫描记录 3. 开始扫描		1
	Mobi_100215	常驻通知栏拉活心跳
（创建子线程 时上报一次，之后每隔10分钟上报一次打点 msg  传当前线程名称）		拉活时上报一次，之后每隔10分钟上报一次打点		1
			msg	传当前线程名称		1
	Mobi_100216	常驻通知栏拉活唤醒次数（应用活的情况下  创建子线程时上报  msg  传当前线程名称）		每次唤醒时上报		1
			msg	传当前线程名称		1
	Mobi_100217	创建前台服务拉起成功	msg	当前的线程名称		1
	Mobi_100218	创建前台服务拉起失败	msg	当前的线程名称		1
	Mobi_100219	通知栏消息满足条件（总点： FCM+广播触发）				1
	Mobi_100220	通知栏消息展示（总点： FCM+广播触发）				1
	Mobi_100221	通知栏消息点击（总点 ：FCM+广播触发）				1
	Mobi_100222	FCM通知栏接收到消息（新版）（只有在解锁屏幕后，收到FCM且满足间隔时间才打）	type			1
	Mobi_100223	通知栏消息满足条件（新版）（总点： FCM（只有在解锁屏幕后，收到FCM且满足间隔时间才打）+广播触发）				1
	Mobi_100224	13以上系统在loading时弹出系统默认通知栏权限弹窗展示				1
	Mobi_100225	13以上系统在loading时弹出系统默认通知栏权限弹窗点击	type	1.同意 2.拒绝		1
回切应用	Mobi_100301	回切应用开屏动画展现				1
	Mobi_100302	回切应用开屏动画loading结束				1
	Mobi_100304	回切应用使用首页预加载广告展示				1
	Mobi_100305	回切应用使用加载开屏插页展示				1
首页	Mobi_100401	首页点击QR code Scan				1
	Mobi_100402	首页点击Barcode Scan				1
	Mobi_100403	首页点击Food Scan				1
	Mobi_100404	首页退出APP确认弹窗展示				1
	Mobi_100405	首页退出APP确认弹窗点击exit				1
	Mobi_100406	首次安装启动语言选择页展示				1
	Mobi_100407	首次安装启动语言选择页点击next				1
	Mobi_100408	首次安装启动功能介绍页展示			1.2.0.0版本	1
	Mobi_100409	首次安装启动功能介绍页最后一页点击start			1.2.0.0版本	1
	Mobi_100411	首页点击 Document Scan			1.3.0.0版本	
	Mobi_100412	首页点击 Business Card			1.3.0.0版本	
扫描页	Mobi_100501	系统相机权限获取弹窗展示				1
	Mobi_100502	系统相机权限获取成功		每天只上报1次		1
	Mobi_100503	扫描页展示	type	1. 二维码扫描 2.条形码扫描 3.食物条形码扫描 		1
	Mobi_100504	相机扫描成功	type	1. 二维码扫描 2.条形码扫描 3.食物条形码扫描 		1
	Mobi_100505	扫描页点击关闭按钮或点击物理回退	type	1. 二维码扫描 2.条形码扫描 3.食物条形码扫描 		1
	Mobi_100506	扫描页点击Album				1
	Mobi_100507	相册扫描页展示				1
	Mobi_100508	相册扫描页点击scan				1
	Mobi_100509	相册扫描	type	1. 二维码扫描 2.条形码扫描 3.食物条形码扫描 		1
			type1	1. 成功 2.失败		1
扫描结果页展示	Mobi_100601	扫描结果页展示	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100602	扫描结果页保存图片成功	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100603	扫描结果页点击打开	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100604	扫描结果页点击复制	type	1. 二维码扫描结果页 2.条形码扫描结果页		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100605	扫描结果页点击收藏	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100606	扫描结果页点击返回或点击物理返回	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
	Mobi_100607	扫描结果页删除成功	type	1. 二维码扫描结果页 2.条形码扫描结果页 		1
			type1	1. Website 2.Text 3. Contact 4. Email 5.WIFI 6. 日历事件 7.Address 8. whapsapp 9.Facebook 10.Instagram 11.Spotify 12. X 13. youtube 14. paypal 15.条形码 16. 其他		1
记录页	Mobi_100701	记录页展示	type	1. scanning 2. creat 3.Favorites		1
	Mobi_100702	记录页点击内容	type	1. scanning 2. creat 3.Favorites		1
	Mobi_100703	所有记录删除成功				1
我的	Mobi_100801	我的页面展示				1
	Mobi_100802	我的页面关闭震动				1
	Mobi_100803	我的页面关闭自动复制				1
广告初始化之前 向欧洲经济区(EEA)和英国境内的用户征求意见的适配	Mobi_100782	同意表单可用，加载表单	 	 		1
	Mobi_100783	同意信息更新失败	 	 		1
	Mobi_100784	同意表单不可用	 	 		1
	Mobi_100785	表单加载失败时 或 表单加载完并显示成功并且用户操作完表单后	agree	用户点击同意		1
创建二维码	Mobi_100901	创建二维码页面展示				1
	Mobi_100902	创建二维码点击类型	type	1. 粘贴板 2.Website 3.Barcode 4. Text 5.Contact 6.Email 7.WIFI 8.Facebook 9. Whatsapp 10.Instagram 11.Spotify 12.X 13. Youtube 14. Paypal 15. Event 16. Address		1
	Mobi_100903	创建二维码点击creat	type	1. 粘贴板 2.Website 3.Barcode 4. Text 5.Contact 6.Email 7.WIFI 8.Facebook 9. Whatsapp 10.Instagram 11.Spotify 12.X 13. Youtube 14. Paypal 15. Event 16. Address		1
	Mobi_100904	创建二维码结果页展示	type	1. 粘贴板 2.Website 3.Barcode 4. Text 5.Contact 6.Email 7.WIFI 8.Facebook 9. Whatsapp 10.Instagram 11.Spotify 12.X 13. Youtube 14. Paypal 15. Event 16. Address		1
	Mobi_100905	创建二维码结果页点击	type	1. Favorite 2.open 3. Regenerate 4.Delete		1
	Mobi_100906	创建二维码结果页保存至相册				1
	Mobi_100907	创建二维码结果点击返回或物理返回				1
	Mobi_100908	编辑二维码页面展示	type	1. 从创建二维码页面进入 2.从扫描二维码结果页进入 3.从历史记录页面进入（含扫描记录、收藏记录、创建纪录）	1.2.0.0版本	1
	Mobi_100909	编辑二维码弹窗展示	type	1. Colors  2. Logo  3.Background	1.2.0.0版本	1
	Mobi_100910	编辑二维码弹窗点击确认（弹窗右上角✔按钮）	type	1. Colors  2. Logo  3.Background	1.2.0.0版本	1
	Mobi_100911	编辑二维码页面点击save按钮			1.2.0.0版本	1
	Mobi_100912	编辑二维码页页面放弃弹窗点击“discard”			1.2.0.0版本	1
文件扫描	Mobi_101001	文件扫描页展示			1.3.0.0版本	
	Mobi_101002	文件扫描结果页展示				
	Mobi_101003	文件扫描结果页点击exit或点击返回或点击物理返回				
	Mobi_101004	文件结果页点击	type	1. Save to Album 2. Save to Local 3.Delete 4.Favorite 5. Rescan		
名片生成	Mobi_101101	名片模板列表页展示（切换顶部tab也统计一次展示）				
	Mobi_101102	名片模板预览页展示				
	Mobi_101103	名片模板预览页点击exit、左上角返回、物理回退				
	Mobi_101104	名片模板页edit弹窗展示				
	Mobi_101105	名片模板页点击save				
	Mobi_101106	名片结果页展示				
	Mobi_101107	名片生成结果页点击左上角返回或点击物理返回				
	Mobi_101108	名片结果页点击Save to Album				
广告show方法	Mobi_101301	调用广告展示show方法的时候上报	scene	广告场景ID		1
配置接口/归因	Mobi_101701	判断用户属性	type	0 未归因  1 自然用户   2 广告用户		
	Mobi_101702	判断用户属性发生变化	type	1: 0->1(未归因->自然用户)
2: 0->2(未归因->广告用户)
3: 1->2(自然用户·>广告用户)
4: 1->0(自然用户.>未归因用户)
5: 2->0(广告用户·>未归因用户)
6: 2->1(广告用户.>自然用户)		
	Mobi_101703	请求配置接口	type	1.成功 2.失败		
			msg	失败原因		
			count	单次进程连续请求失败的次数，请求成功后不再上报		
			success_times	单次进程第几次请求成功，请求成功后不再上报		
	Mobi_101704	请求归因接口	type	1.成功 2.失败		
			msg	失败原因		
	Mobi_101705	归因接口请求失败，用本地保存的用户属性	type	0 未归因  1 自然用户   2 广告用户		
	Mobi_101706	发起配置接口请求次数				
	Mobi_101707	发起归因接口请求次数				
	Mobi_101708	FB==EVENT_NAME_ADDED_TO_PURCHASE	msg	异常原因		
	Mobi_101709	FB==EVENT_NAME_ADDED_TO_CART	msg	异常原因		
	Mobi_101710	adjust，客户端utm_c_source、utm_campaign_id有值时，强制转变为广告归因逻辑				
"""

private fun main() {
    val trimStart = excel.trimIndent()
    val dotInfo = trimStart.split("Mobi_")
    for (infos in dotInfo) {
        val regex = Regex("""^(\d+)""")
        regex.find(infos)?.groupValues?.get(1)?.let {
            val units = infos.split("\t").filter { it.isNotBlank() }
            println(createOutput(units))
        }
    }
}

private fun createOutput(units:List<String>):String{
    val id = units[0]
    val dotName = units[1]
    val idName = replaceId(id)

    return """
    /** $id $dotName */
    const val $idName = "$id"
    """.trimIndent().split("\n").joinToString("\n") { "    $it" }
}

private fun replaceId(id:String):String{
    val idName = StringBuilder()
    for (c in id) {
        val newChar = when(c){
            '1'-> 'y'
            '2'-> 'e'
            '3'-> 'x'
            '4'-> 's'
            '5'-> 'w'
            '6'-> 'z'
            '7'-> 'q'
            '8'-> 'b'
            '9'-> 'j'
            '0'-> 'l'
            else->'a'
        }
        idName.append(newChar)
    }
    return idName.toString()
}