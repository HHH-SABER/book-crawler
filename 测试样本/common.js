function qsskel(o){function w(b,a){return(b<<a)|(b>>>(32-a))}function E(k,b){var U,a,d,x,c;d=(k&2147483648);x=(b&2147483648);U=(k&1073741824);a=(b&1073741824);c=(k&1073741823)+(b&1073741823);if(U&a){return(c^2147483648^d^x)}if(U|a){if(c&1073741824){return(c^3221225472^d^x)}else{return(c^1073741824^d^x)}}else{return(c^d^x)}}function s(a,c,b){return(a&c)|((~a)&b)}function r(a,c,b){return(a&b)|(c&(~b))}function q(a,c,b){return(a^c^b)}function p(a,c,b){return(c^(a|(~b)))}function f(V,U,Z,Y,k,W,X){V=E(V,E(E(s(U,Z,Y),k),X));return E(w(V,W),U)}function C(V,U,Z,Y,k,W,X){V=E(V,E(E(r(U,Z,Y),k),X));return E(w(V,W),U)}function t(V,U,Z,Y,k,W,X){V=E(V,E(E(q(U,Z,Y),k),X));return E(w(V,W),U)}function e(V,U,Z,Y,k,W,X){V=E(V,E(E(p(U,Z,Y),k),X));return E(w(V,W),U)}function g(k){var V;var d=k.length;var c=d+8;var b=(c-(c%64))/64;var U=(b+1)*16;var W=Array(U-1);var a=0;var x=0;while(x<d){V=(x-(x%4))/4;a=(x%4)*8;W[V]=(W[V]|(k.charCodeAt(x)<<a));x++}V=(x-(x%4))/4;a=(x%4)*8;W[V]=W[V]|(128<<a);W[U-2]=d<<3;W[U-1]=d>>>29;return W}function G(c){var b="",d="",k,a;for(a=0;a<=3;a++){k=(c>>>(a*8))&255;d="0"+k.toString(16);b=b+d.substr(d.length-2,2)}return b}function u(b){b=b.replace(/\r\n/g,"\n");var a="";for(var k=0;k<b.length;k++){var d=b.charCodeAt(k);if(d<128){a+=String.fromCharCode(d)}else{if((d>127)&&(d<2048)){a+=String.fromCharCode((d>>6)|192);a+=String.fromCharCode((d&63)|128)}else{a+=String.fromCharCode((d>>12)|224);a+=String.fromCharCode(((d>>6)&63)|128);a+=String.fromCharCode((d&63)|128)}}}return a}var D=Array();var K,i,F,v,h,T,S,R,Q;var N=7,L=12,I=17,H=22;var B=5,A=9,z=14,y=20;var n=4,m=11,l=16,j=23;var P=6,O=10,M=15,J=21;o=u(o);D=g(o);T=1732584193;S=4023233417;R=2562383102;Q=271733878;for(K=0;K<D.length;K+=16){i=T;F=S;v=R;h=Q;T=f(T,S,R,Q,D[K+0],N,3614090360);Q=f(Q,T,S,R,D[K+1],L,3905402710);R=f(R,Q,T,S,D[K+2],I,606105819);S=f(S,R,Q,T,D[K+3],H,3250441966);T=f(T,S,R,Q,D[K+4],N,4118548399);Q=f(Q,T,S,R,D[K+5],L,1200080426);R=f(R,Q,T,S,D[K+6],I,2821735955);S=f(S,R,Q,T,D[K+7],H,4249261313);T=f(T,S,R,Q,D[K+8],N,1770035416);Q=f(Q,T,S,R,D[K+9],L,2336552879);R=f(R,Q,T,S,D[K+10],I,4294925233);S=f(S,R,Q,T,D[K+11],H,2304563134);T=f(T,S,R,Q,D[K+12],N,1804603682);Q=f(Q,T,S,R,D[K+13],L,4254626195);R=f(R,Q,T,S,D[K+14],I,2792965006);S=f(S,R,Q,T,D[K+15],H,1236535329);T=C(T,S,R,Q,D[K+1],B,4129170786);Q=C(Q,T,S,R,D[K+6],A,3225465664);R=C(R,Q,T,S,D[K+11],z,643717713);S=C(S,R,Q,T,D[K+0],y,3921069994);T=C(T,S,R,Q,D[K+5],B,3593408605);Q=C(Q,T,S,R,D[K+10],A,38016083);R=C(R,Q,T,S,D[K+15],z,3634488961);S=C(S,R,Q,T,D[K+4],y,3889429448);T=C(T,S,R,Q,D[K+9],B,568446438);Q=C(Q,T,S,R,D[K+14],A,3275163606);R=C(R,Q,T,S,D[K+3],z,4107603335);S=C(S,R,Q,T,D[K+8],y,1163531501);T=C(T,S,R,Q,D[K+13],B,2850285829);Q=C(Q,T,S,R,D[K+2],A,4243563512);R=C(R,Q,T,S,D[K+7],z,1735328473);S=C(S,R,Q,T,D[K+12],y,2368359562);T=t(T,S,R,Q,D[K+5],n,4294588738);Q=t(Q,T,S,R,D[K+8],m,2272392833);R=t(R,Q,T,S,D[K+11],l,1839030562);S=t(S,R,Q,T,D[K+14],j,4259657740);T=t(T,S,R,Q,D[K+1],n,2763975236);Q=t(Q,T,S,R,D[K+4],m,1272893353);R=t(R,Q,T,S,D[K+7],l,4139469664);S=t(S,R,Q,T,D[K+10],j,3200236656);T=t(T,S,R,Q,D[K+13],n,681279174);Q=t(Q,T,S,R,D[K+0],m,3936430074);R=t(R,Q,T,S,D[K+3],l,3572445317);S=t(S,R,Q,T,D[K+6],j,76029189);T=t(T,S,R,Q,D[K+9],n,3654602809);Q=t(Q,T,S,R,D[K+12],m,3873151461);R=t(R,Q,T,S,D[K+15],l,530742520);S=t(S,R,Q,T,D[K+2],j,3299628645);T=e(T,S,R,Q,D[K+0],P,4096336452);Q=e(Q,T,S,R,D[K+7],O,1126891415);R=e(R,Q,T,S,D[K+14],M,2878612391);S=e(S,R,Q,T,D[K+5],J,4237533241);T=e(T,S,R,Q,D[K+12],P,1700485571);Q=e(Q,T,S,R,D[K+3],O,2399980690);R=e(R,Q,T,S,D[K+10],M,4293915773);S=e(S,R,Q,T,D[K+1],J,2240044497);T=e(T,S,R,Q,D[K+8],P,1873313359);Q=e(Q,T,S,R,D[K+15],O,4264355552);R=e(R,Q,T,S,D[K+6],M,2734768916);S=e(S,R,Q,T,D[K+13],J,1309151649);T=e(T,S,R,Q,D[K+4],P,4149444226);Q=e(Q,T,S,R,D[K+11],O,3174756917);R=e(R,Q,T,S,D[K+2],M,718787259);S=e(S,R,Q,T,D[K+9],J,3951481745);T=E(T,i);S=E(S,F);R=E(R,v);Q=E(Q,h)}return(G(T)+G(S)+G(R)+G(Q)).toLowerCase()};

jq = jQuery.noConflict();//重定义JQ
var varslehj3 = qsskel(jq.cookie('user_id') + jq.cookie('user_name') + kdeh2);
if(jq.cookie('user_name')){//登录判断
	var user_name = jq.cookie('user_name');
	jq('#qs_login').html('<a href=\"/mybook.html\" title=\"访问会员书架\">'+user_name+'</a><a href=\"javascript:qs_logout();\">退出</a>');
}else{
	jq('#qs_login').html('<a href=\"/login.html?url='+lg_url+'\">登录</a><a href=\"/register.html?url='+lg_url+'\">注册</a>');
}

function qs_logout(){//退出登录
	jq.removeCookie(varslehj3,{ path: '/'});
	jq.removeCookie('user_id',{ path: '/'});
	jq.removeCookie('user_name',{ path: '/'});
	window.location.reload();
}

function login(lg_url){//用户登录
	user_name = document.getElementById("user_name").value;
	user_pass = qsskel(document.getElementById("user_pass").value);
	user_code = document.getElementById("user_code").value;
	jq.post('/qs_login_go.php',{'user_name':user_name,'user_pass':user_pass,'user_code':user_code},
	function(data){
		data=data.replace(/\s/g,'');data=data.split("|");
		erword=data[1];
		if(data[0]==1){
			window.location.href = lg_url;
		}
		else{
			reloadcode();
			jq('#shuqian').html('<div class=\"dvfd\"><span class=red>'+erword+'</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>');
		}
	});
}

function register(lg_url){//用户注册
	name = document.getElementById("name").value;
	mobile = document.getElementById("mobile").value;
	pass = qsskel(document.getElementById("pass").value);
	pass2 = qsskel(document.getElementById("pass2").value);
	code = document.getElementById("code").value;
	if(pass == pass2){
		jq.post('/qs_register_go.php',{'name':name,'mobile':mobile,'pass':pass,'pass2':pass2,'code':code},
		function(data){
			data=data.replace(/\s/g,'');data=data.split('|');
			erword=data[1];
			if(data[0]==1){
				window.location.href = lg_url;
			}
			else{
				reloadcode();
				jq('#shuqian').html('<div class=\"dvfd\"><span class=red>'+erword+'</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>');
			}
		});
	}else{
		reloadcode();
		jq('#shuqian').html('<div class=\"dvfd\"><span class=red>两次密码不一致</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>');
	}
}


function case_del(aid,xstitle){//从书架删除小说
	jq.post("/ajax.php",{"aid":aid,"case_del":"1"},function(data){
		jq("#"+aid).html("<span class=\"s5\">删除中</span>");if(data != ""){
			jq("#"+aid).html("<span class=\"s5\">已删除</span>");
		}
	});
}


function shanchusc(){document.getElementById('shuqian').innerHTML = '';}//清空shuqian DIV
function addbookcase(url,aid){//添加小说到书架
	jq.get('/ajax.php',{'addbookcase':'1','url':url,'aid':aid},
		function(data){
			data=data.replace(/\s/g,'');data=data.split("|");
			if(data[0]==1){
				jq('#shuqian').animate({left:"-5px"},20).animate({left:"10px"},20).animate({left:"-10px"},20).animate({left:"0px"},20).html('<div class=\"dvfd\"><span class=red>添加成功</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>');
			}
			else{
				window.location.href = "/login.html?url="+data[1];
			}
		});
}
function shuqian(aid,cid,url){//存书签
	//alert("shuqian");	
	jq.get('/ajax.php',{'addmark':'1','url':url,'aid':aid,'cid':cid},
		function(data){
			data=data.replace(/\s/g,'');data=data.split("|");
			if(data[0]==1){
				jq('#shuqian').animate({left:"-5px"},20).animate({left:"10px"},20).animate({left:"-10px"},20).animate({left:"0px"},20).html('<div class=\"dvfd\"><span class=red>书签已保存</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>');
			}
			else{
				window.location.href = "/login.html?url="+data[1];
			}
		});
}
function shuqian2(t){
	var t = t.replace(/\s/g,'');
	//alert(t);
	var a = t.split("|");
	if(a[0]==1){
		jq("#shuqian").html("<div class=\"dvfd\"><span class=red>收藏成功</span><a href=\"javascript:shanchusc();\" class=\"qdbtn\">确  定</a></div>");
	}
	if(a[0]==0){
		window.location.href = "/login.php?url="+a[1];
	}
}