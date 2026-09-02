var qsbs={_keyStr:"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",aa:function(input){var output="";var chr1,chr2,chr3,enc1,enc2,enc3,enc4;var i=0;input=qsbs._utf8_encode(input);while(i<input.length){chr1=input.charCodeAt(i++);chr2=input.charCodeAt(i++);chr3=input.charCodeAt(i++);enc1=chr1>>2;enc2=((chr1&3)<<4)|(chr2>>4);enc3=((chr2&15)<<2)|(chr3>>6);enc4=chr3&63;if(isNaN(chr2)){enc3=enc4=64}else if(isNaN(chr3)){enc4=64}output=output+this._keyStr.charAt(enc1)+this._keyStr.charAt(enc2)+this._keyStr.charAt(enc3)+this._keyStr.charAt(enc4)}return output},bb:function(input){var output="";var chr1,chr2,chr3;var enc1,enc2,enc3,enc4;var i=0;input=input.replace(/[^A-Za-z0-9\+\/\=]/g,"");while(i<input.length){enc1=this._keyStr.indexOf(input.charAt(i++));enc2=this._keyStr.indexOf(input.charAt(i++));enc3=this._keyStr.indexOf(input.charAt(i++));enc4=this._keyStr.indexOf(input.charAt(i++));chr1=(enc1<<2)|(enc2>>4);chr2=((enc2&15)<<4)|(enc3>>2);chr3=((enc3&3)<<6)|enc4;output=output+String.fromCharCode(chr1);if(enc3!=64){output=output+String.fromCharCode(chr2)}if(enc4!=64){output=output+String.fromCharCode(chr3)}}output=qsbs._utf8_decode(output);return output},_utf8_encode:function(string){string=string.replace(/\r\n/g,"\n");var utftext="";for(var n=0;n<string.length;n++){var c=string.charCodeAt(n);if(c<128){utftext+=String.fromCharCode(c)}else if((c>127)&&(c<2048)){utftext+=String.fromCharCode((c>>6)|192);utftext+=String.fromCharCode((c&63)|128)}else{utftext+=String.fromCharCode((c>>12)|224);utftext+=String.fromCharCode(((c>>6)&63)|128);utftext+=String.fromCharCode((c&63)|128)}}return utftext},_utf8_decode:function(utftext){var string="";var i=0;var c=c1=c2=0;while(i<utftext.length){c=utftext.charCodeAt(i);if(c<128){string+=String.fromCharCode(c);i++}else if((c>191)&&(c<224)){c2=utftext.charCodeAt(i+1);string+=String.fromCharCode(((c&31)<<6)|(c2&63));i+=2}else{c2=utftext.charCodeAt(i+1);c3=utftext.charCodeAt(i+2);string+=String.fromCharCode(((c&15)<<12)|((c2&63)<<6)|(c3&63));i+=3}}return string}}
var _num = 100;

function LastRead(){
	this.bookList="bookList"
	}
LastRead.prototype={
	set:function(bid,tid,title,texttitle,read_page,author,tmpbook){
		if(!(bid&&tid&&title&&texttitle,read_page))return;
		var v=bid+'#'+tid+'#'+title+'#'+texttitle+'#'+read_page+'#'+author+'#'+tmpbook;
		this.setItem(bid,v);
		this.setBook(bid)
		},

	get:function(k){
		return this.getItem(k)?this.getItem(k).split("#"):"";
		},

	remove:function(k){
		this.removeItem(k);
		this.removeBook(k)
		},

	setBook:function(v){
		var reg=new RegExp("(^|#)"+v);
		var books =	this.getItem(this.bookList);
		if(books==""){
			books=v
			}
		 else{
			 if(books.search(reg)==-1){
				 books+="#"+v
				 }
			 else{
				  books.replace(reg,"#"+v)
				 }
			 }
			this.setItem(this.bookList,books)

		},

	getBook:function(){
		var v=this.getItem(this.bookList)?this.getItem(this.bookList).split("#"):Array();
		var books=Array();
		if(v.length){

			for(var i=0;i<v.length;i++){
				var tem=this.getItem(v[i]).split('#');
				if(i>v.length-(_num+1)){
					if (tem.length>3)	books.push(tem);
				}
				else{
					lastread.remove(tem[0]);
				}
			}
		}
		return books
	},

	removeBook:function(v){
	    var reg=new RegExp("(^|#)"+v);
		var books =	this.getItem(this.bookList);
		if(!books){
			books=""
			}
		 else{
			 if(books.search(reg)!=-1){
			      books=books.replace(reg,"")
				 }

			 }
			this.setItem(this.bookList,books)

		},

	setItem:function(k,v){
		if(!!window.localStorage){
			localStorage.setItem(k,v);
		}
		else{
			var expireDate=new Date();
			  var EXPIR_MONTH=30*24*3600*1000;
			  expireDate.setTime(expireDate.getTime()+12*EXPIR_MONTH)
			  document.cookie=k+"="+encodeURIComponent(v)+";expires="+expireDate.toGMTString()+"; path=/";
			}
		},

	getItem:function(k){
		var value=""
		var result=""
		if(!!window.localStorage){
			result=window.localStorage.getItem(k);
			 value=result||"";
		}
		else{
			var reg=new RegExp("(^| )"+k+"=([^;]*)(;|\x24)");
			var result=reg.exec(document.cookie);
			if(result){
				value=decodeURIComponent(result[2])||""}
		}
		return value

		},

	removeItem:function(k){
		if(!!window.localStorage){
		 window.localStorage.removeItem(k);
		}
		else{
			var expireDate=new Date();
			expireDate.setTime(expireDate.getTime()-1000)
			document.cookie=k+"= "+";expires="+expireDate.toGMTString()
		}
		},
	removeAll:function(){
		if(!!window.localStorage){
		 window.localStorage.clear();
		}
		else{
		var v=this.getItem(this.bookList)?this.getItem(this.bookList).split("#"):Array();
		var books=Array();
		if(v.length){
			for( i in v ){
				var tem=this.removeItem(v[k])
				}
			}
			this.removeItem(this.bookList)
		}
		}
}

function showbook(){
	var showbook=document.getElementById('tmpbook');
	var books=lastread.getBook();
	var bookhtml = '<li><span class="s1">小说名称</span><span class="s2">作者</span><span class="s3">最后阅读章节</span><span class="s5">操 作</span></li>';
	if(books.length){
		var k = 1;
		for(var i=books.length-1;i>-1;i--){
			var articlename = books[i][2];
			var lastchapter = books[i][3];
			var lastchapterid = books[i][1];
			var read_page = parseInt(books[i][4]);
			var tmpbook_del = books[i][0];
			var author = books[i][5];
			var read_ym = parseInt(read_page+1);
			if(books[i][6]>0){
				var articleid = parseInt(books[i][0].replace('t',''));
				var shortid = parseInt(articleid/1000);
				var mybook_aid = parseInt(books[i][6]);
				var mybook_cid = parseInt(books[i][1] - articleid);
				info_url = tag_info_rewrite.replace(/{aid}/, articleid);
				info_url = info_url.replace(/{bid}/, shortid);
				read_url = tag_read_rewrite.replace(/{aid}/, articleid);
				read_url = read_url.replace(/{bid}/,shortid);
				read_url = read_url.replace(/{cid}/,lastchapterid);
				read_page_url = tag_read_page_rewrite.replace(/{aid}/, articleid);
				read_page_url = read_page_url.replace(/{bid}/,shortid);
				read_page_url = read_page_url.replace(/{cid}/,lastchapterid);
				read_page_url = read_page_url.replace(/{pid}/,read_page);
			}else{
				var articleid = parseInt(books[i][0]);
				var shortid = parseInt(articleid/1000);
				var mybook_aid = articleid;
				var mybook_cid = books[i][1];
				info_url = info_rewrite.replace(/{aid}/, articleid);
				info_url = info_url.replace(/{bid}/, shortid);
				read_url = read_rewrite.replace(/{aid}/, articleid);
				read_url = read_url.replace(/{bid}/,shortid);
				read_url = read_url.replace(/{cid}/,lastchapterid);
				read_page_url = read_page_rewrite.replace(/{aid}/, articleid);
				read_page_url = read_page_url.replace(/{bid}/,shortid);
				read_page_url = read_page_url.replace(/{cid}/,lastchapterid);
				read_page_url = read_page_url.replace(/{pid}/,read_page);
			}
			var info_url,read_url;
			var c = '';
			if((k % 2) == 0){
				c = 'hot_saleEm';
			}
	   if(read_page == 0){
		page_word='';
	     }else{
            page_word='第'+read_ym+'页';
	     }
		if(read_page == 0){
			jxyd ='<a href="'+read_url+'" class="a3"><span class="iconfont icon-yuedu1"></span>继续阅读</a></div>';
		}else{
			jxyd ='<a href="'+read_page_url+'" class="a3"><span class="iconfont icon-yuedu1"></span>继续阅读</a></div>';
		}
		var jxyd;
		bookhtml+='<li id="'+tmpbook_del+'"><span class="s1"><a href="'+info_url+'">'+articlename+'</a></span><span class="s2">'+author+'</span><span class="s3">'+lastchapter+page_word+'</span><span class="s5">'+jxyd+'<a onclick=\'shuqian('+mybook_aid+','+mybook_cid+',"'+tmpbook_rewrite+'")\' class="a2"><span class="iconfont icon-gengxin"></span>保存至会员书架</a><a href="javascript:removebook('+tmpbook_del+')" class="xsdel">删除</a></span></li>';
		k++;
		}
		showbook.innerHTML = bookhtml;
	}
	else{
		showbook.innerHTML = '<li>您还木有阅读本站小说，未产生阅读记录。</li>';
	}


}

function removebook(k){
	lastread.remove(k);
	showbook()
}



function yuedu(){
	//document.write("<a href='javascript:showbook();' target='_self'>点击查看阅读记录</a>");
	showbook();
}

window.lastread = new LastRead();


function removebook(k){
	lastread.remove(k);
	showbook()
}




