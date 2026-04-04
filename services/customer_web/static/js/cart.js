/**
 * cart.js — 장바구니 UI 갱신
 *
 * 외부에서 updateCart(items) 를 호출하면 #cart-list, #cart-total 을 갱신한다.
 * is_paid 항목: ✓ 표시 + [✕] 비활성화
 * 미결제 항목: [✕] 클릭 → deleteItem(item_id) 호출
 */

/* global socket, showToast */

"use strict";

/**
 * 장바구니 항목 배열로 UI를 갱신한다.
 * @param {Array<{id: number, name: string, price: number, is_paid: boolean}>} items
 */
function updateCart(items) {
  const list  = document.getElementById("cart-list");
  const total = document.getElementById("cart-total-amount");
  const paymentList = document.getElementById("payment-cart-list");
  const paymentTotal = document.getElementById("payment-total-amount");

  if (!list) return;

  if (!items || items.length === 0) {
    list.innerHTML = '<li class="cart-empty">장바구니가 비어있습니다.</li>';
    if (total) total.textContent = "0원";
    _updatePaymentModal([], paymentList, paymentTotal);
    return;
  }

  let sum = 0;
  list.innerHTML = "";

  items.forEach((item) => {
    sum += item.price || 0;

    const li = document.createElement("li");
    li.className = "cart-item";
    li.dataset.itemId = item.id;

    const nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = item.name;

    const priceSpan = document.createElement("span");
    priceSpan.className = "item-price";
    priceSpan.textContent = _formatPrice(item.price);

    if (item.is_paid) {
      const paidMark = document.createElement("span");
      paidMark.className = "item-paid";
      paidMark.textContent = "✓";

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-delete";
      deleteBtn.disabled = true;
      deleteBtn.setAttribute("aria-label", "삭제 불가 (결제완료)");
      deleteBtn.textContent = "✕";

      li.append(nameSpan, priceSpan, paidMark, deleteBtn);
    } else {
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-delete";
      deleteBtn.setAttribute("aria-label", `${item.name} 삭제`);
      deleteBtn.textContent = "✕";
      deleteBtn.addEventListener("click", () => deleteItem(item.id));

      li.append(nameSpan, priceSpan, deleteBtn);
    }

    list.appendChild(li);
  });

  if (total) total.textContent = _formatPrice(sum);

  // 결제 팝업 목록도 동기화
  _updatePaymentModal(items, paymentList, paymentTotal);
}

/**
 * 결제 팝업 내 장바구니 목록 갱신.
 */
function _updatePaymentModal(items, listEl, totalEl) {
  if (!listEl) return;

  if (!items || items.length === 0) {
    listEl.innerHTML = '<li class="cart-empty">장바구니가 비어있습니다.</li>';
    if (totalEl) totalEl.textContent = "0원";
    return;
  }

  let sum = 0;
  listEl.innerHTML = "";

  items.forEach((item) => {
    sum += item.price || 0;
    const li = document.createElement("li");
    li.className = "cart-item";

    const nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = item.name;

    const priceSpan = document.createElement("span");
    priceSpan.className = "item-price";
    priceSpan.textContent = _formatPrice(item.price);

    li.append(nameSpan, priceSpan);
    listEl.appendChild(li);
  });

  if (totalEl) totalEl.textContent = _formatPrice(sum);
}

/**
 * 장바구니 항목에서 미결제 항목이 있는지 확인한다.
 * @returns {boolean}
 */
function hasUnpaidItems() {
  const items = document.querySelectorAll("#cart-list .cart-item");
  for (const li of items) {
    const paidMark = li.querySelector(".item-paid");
    if (!paidMark) return true; // ✓ 없으면 미결제
  }
  return false;
}

/**
 * 항목 삭제 요청. socket.js 의 socket 객체 사용.
 * @param {number} itemId
 */
function deleteItem(itemId) {
  if (typeof socket !== "undefined" && socket) {
    socket.emit("delete_item", { item_id: itemId });
  }
}

/**
 * 가격을 "1,500원" 형식으로 포맷.
 * @param {number} price
 * @returns {string}
 */
function _formatPrice(price) {
  return (price || 0).toLocaleString("ko-KR") + "원";
}
