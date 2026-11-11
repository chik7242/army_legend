const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor?.("#1b1015"); tg.setBackgroundColor?.("#1b1015"); }

const API_BASE = "https://YOUR-BACKEND.onrender.com"; // Замените на адрес вашего Python backend
const CHANNEL_URL = "https://t.me/YOUR_CHANNEL";
const SUPPORT_URL = "https://t.me/YOUR_SUPPORT";

document.getElementById("channelLink").href = CHANNEL_URL;
document.getElementById("chatLink").href = SUPPORT_URL;

const products = [
  {id:"cry4me",name:"CRY4ME",category:"Игры",platforms:["Android"],subtitle:"Софт на Android",description:"Цифровой продукт для Android. Перед покупкой проверьте совместимость устройства и описание поставки.",status:"В обновлении",sale:true,plans:[["1 День",200],["7 Дней",750],["30 Дней",2100],["Навсегда",7500]]},
  {id:"jarvis",name:"JARVIS",category:"Игры",platforms:["Android"],subtitle:"Без root-прав",description:"Цифровой продукт для Android. Информация о версии и совместимости уточняется в карточке товара.",status:"Обновлён",sale:false,plans:[["1 День",210],["7 Дней",790],["30 Дней",2200],["Навсегда",7900]]},
  {id:"deadnight",name:"DeadNight",category:"Игры",platforms:["Android","PC"],subtitle:"Android и PC · без root-прав",description:"Цифровой продукт для Android и PC. Уточните системные требования перед оплатой.",status:"В обновлении",sale:true,plans:[["1 День",150],["7 Дней",550],["30 Дней",1500],["Навсегда",5900]]},
  {id:"ios-pack",name:"iPhone CHEAT",category:"Игры",platforms:["iOS"],subtitle:"iOS",description:"Цифровой продукт для iOS. Проверьте поддерживаемую версию iOS и способ активации.",status:"В наличии",sale:false,plans:[["1 День",250],["7 Дней",900],["30 Дней",2500],["Навсегда",8500]]},
  {id:"android-pack",name:"ANDROID CHEAT",category:"Игры",platforms:["Android"],subtitle:"Без root-прав",description:"Подборка цифровых продуктов для Android. Доступность зависит от выбранного тарифа.",status:"В наличии",sale:false,plans:[["1 День",150],["7 Дней",600],["30 Дней",1700],["Навсегда",6500]]}
];
let selectedPlatform="all", currentProduct=null, selectedPlan=0, activeTab="catalog";
const $=id=>document.getElementById(id);
const money=n=>`${Number(n).toLocaleString("ru-RU")} ⭐`;
function minPrice(p){return Math.min(...p.plans.map(x=>x[1]));}
function art(p){return `<div class="product-art">${p.sale?'<span class="sale-tag">РАСПРОДАЖА</span>':''}<div class="art-label">${p.name}<small>${p.subtitle}</small></div></div>`;}
function renderCatalog(){
 const q=$("searchInput").value.trim().toLowerCase();
 const list=products.filter(p=>(selectedPlatform==="all"||p.platforms.includes(selectedPlatform))&&(`${p.name} ${p.subtitle} ${p.category}`.toLowerCase().includes(q)));
 $("itemCount").textContent=`${list.length} товара`;
 $("catalogGrid").innerHTML=list.map(p=>`<article class="product-card" data-id="${p.id}">${art(p)}<div class="product-info"><div class="status">● ${p.status}</div><h3>${p.name} · ${p.subtitle}</h3><p>${p.plans.length} тарифа · от ${money(minPrice(p))}</p></div></article>`).join("")||'<div class="empty-state">Ничего не найдено</div>';
 document.querySelectorAll(".product-card").forEach(el=>el.onclick=()=>openProduct(el.dataset.id));
}
function showTab(tab){
 activeTab=tab;
 ["app","productPage","reviewsPage","checkPage","profilePage"].forEach(id=>$(id).classList.add("hidden"));
 if(tab==="catalog")$("app").classList.remove("hidden");
 if(tab==="reviews")$("reviewsPage").classList.remove("hidden");
 if(tab==="check")$("checkPage").classList.remove("hidden");
 if(tab==="profile")$("profilePage").classList.remove("hidden");
 document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
}
function openProduct(id){
 currentProduct=products.find(p=>p.id===id);selectedPlan=0;
 $("app").classList.add("hidden");$("productPage").classList.remove("hidden");
 $("productPage").innerHTML=`<section class="product-detail"><button class="back-btn" id="backCatalog">← Назад</button><div class="detail-art"><div class="art-label">${currentProduct.name}<small>${currentProduct.subtitle}</small></div></div><span class="eyebrow">${currentProduct.category} · ${currentProduct.platforms.join(" / ")}</span><h1 class="detail-title">${currentProduct.name}</h1><p class="detail-description">${currentProduct.description}</p><div class="section-head"><h2>Выберите тариф</h2><span class="muted">Цена за период</span></div><div class="plan-list">${currentProduct.plans.map((p,i)=>`<button class="plan ${i===0?'selected':''}" data-plan="${i}">${p[0]}<b>${money(p[1])}</b></button>`).join("")}</div><button class="primary-btn full" id="buyNow">Купить · ${money(currentProduct.plans[0][1])} <span>↗</span></button></section>`;
 $("backCatalog").onclick=()=>{ $("productPage").classList.add("hidden");$("app").classList.remove("hidden"); };
 document.querySelectorAll(".plan").forEach(b=>b.onclick=()=>{selectedPlan=Number(b.dataset.plan);document.querySelectorAll(".plan").forEach(x=>x.classList.toggle("selected",x===b));$("buyNow").innerHTML=`Купить · ${money(currentProduct.plans[selectedPlan][1])} <span>↗</span>`;});
 $("buyNow").onclick=()=>openCheckout();
}
function openCheckout(){
 const plan=currentProduct.plans[selectedPlan];
 $("checkoutSummary").innerHTML=`<div class="cart-line"><span>${currentProduct.name} · ${plan[0]}</span><b>${money(plan[1])}</b></div>`;
 $("paymentMessage").textContent="";
 $("checkoutModal").classList.remove("hidden");
}
async function pay(){
 if(!tg?.initData){toast("Откройте магазин через Telegram-бота");return;}
 if(API_BASE.includes("YOUR-BACKEND")){toast("Сначала настройте адрес backend в app.js");return;}
 $("payButton").disabled=true;$("payButton").textContent="Создаём счёт…";
 try{
  const res=await fetch(`${API_BASE}/api/create-invoice`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:tg.initData,productId:currentProduct.id,planIndex:selectedPlan})});
  const data=await res.json();if(!res.ok)throw new Error(data.detail||"Не удалось создать счёт");
  $("checkoutModal").classList.add("hidden");
  tg.openInvoice(data.invoice_url,(status)=>{if(status==="paid")toast("Оплата прошла! Бот пришлёт данные заказа.");else if(status==="failed")toast("Платёж не прошёл");});
 }catch(e){$("paymentMessage").textContent=e.message;toast(e.message);}
 finally{$("payButton").disabled=false;$("payButton").innerHTML='Перейти к оплате <span>↗</span>';}
}
function toast(msg){$("toast").textContent=msg;$("toast").classList.add("show");setTimeout(()=>$("toast").classList.remove("show"),2600);}
document.querySelectorAll(".nav-item").forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
document.querySelectorAll(".chip").forEach(b=>b.onclick=()=>{selectedPlatform=b.dataset.platform;document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("active",x===b));renderCatalog();});
$("searchInput").addEventListener("input",renderCatalog);
$("heroCatalog").onclick=()=>$("searchInput").focus();
$("profileShortcut").onclick=()=>showTab("profile");
$("closeModal").onclick=()=>$("checkoutModal").classList.add("hidden");
$("checkoutModal").onclick=e=>{if(e.target===$("checkoutModal"))$("checkoutModal").classList.add("hidden");};
$("payButton").onclick=pay;
$("checkOrder").onclick=async()=>{const id=$("orderCheck").value.trim();if(!id){$("checkResult").textContent="Введите номер заказа.";return;}if(API_BASE.includes("YOUR-BACKEND")){$("checkResult").textContent="Настройте адрес backend в app.js.";return;}try{const r=await fetch(`${API_BASE}/api/order-status?order_id=${encodeURIComponent(id)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:tg?.initData||""})});const d=await r.json();$("checkResult").textContent=r.ok?`Заказ ${d.id}: ${d.status}`:(d.detail||"Заказ не найден");}catch{$("checkResult").textContent="Не удалось связаться с сервером.";}}
function loadProfile(){
 const u=tg?.initDataUnsafe?.user;
 $("profileName").textContent=u?[u.first_name,u.last_name].filter(Boolean).join(" "):"Гость";
 $("profileId").textContent=u?`Telegram ID: ${u.id}`:"Откройте приложение через Telegram";
 $("avatar").textContent=u?.first_name?.[0]?.toUpperCase()||"AL";
}
$("showOrders").onclick=async()=>{if(!tg?.initData){$("ordersList").textContent="Откройте приложение через Telegram.";return;}try{const r=await fetch(`${API_BASE}/api/my-orders`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:tg.initData})});const d=await r.json();$("ordersList").innerHTML=(d.orders||[]).map(o=>`<div class="cart-line"><span>${o.product} · ${o.plan}<br><small>${o.status}</small></span><b>${money(o.price)}</b></div>`).join("")||"Покупок пока нет.";}catch{$("ordersList").textContent="Не удалось загрузить покупки.";}}
loadProfile();renderCatalog();