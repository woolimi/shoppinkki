/**
 * cart.js — 장바구니 UI 갱신
 *
 * updateCart(items) 호출 시 #cart-list, #cart-total 갱신.
 *
 * 항목 구조:
 *   { id, name, price (단가), quantity, is_paid }
 *
 * is_paid=true : ✓ 표시, 수량/삭제 비활성화
 * is_paid=false: [-][수량][+] 수량 편집, [✕] 클릭 → 인라인 삭제 확인
 */

/* global socket, showToast */

"use strict";

/** 마지막으로 받은 장바구니 항목 (인라인 확인 취소 시 복원에 사용) */
let _currentItems = [];

/**
 * 장바구니 항목 배열로 UI를 갱신한다.
 * @param {Array<{id: number, name: string, price: number, quantity: number, is_paid: boolean}>} items
 */
function updateCart(items) {
  _currentItems = items || [];

  const list  = document.getElementById("cart-list");
  const total = document.getElementById("cart-total-amount");
  const paymentList  = document.getElementById("payment-cart-list");
  const paymentTotal = document.getElementById("payment-total-amount");

  if (!list) return;

  if (!_currentItems.length) {
    list.innerHTML = '<li class="cart-empty">장바구니가 비어있습니다.</li>';
    if (total) total.textContent = "0원";
    _updatePaymentModal([], paymentList, paymentTotal);
    return;
  }

  list.innerHTML = "";
  let sum = 0;

  _currentItems.forEach((item) => {
    const qty = item.quantity || 1;
    sum += (item.price || 0) * qty;

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

      const qtyWrap = _buildQtyControl(item.id, qty, true);

      li.append(nameSpan, priceSpan, qtyWrap, paidMark, deleteBtn);
    } else {
      const qtyWrap = _buildQtyControl(item.id, qty, false);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn-delete";
      deleteBtn.setAttribute("aria-label", `${item.name} 삭제`);
      deleteBtn.textContent = "✕";
      deleteBtn.addEventListener("click", () => _onDeleteClick(item.id, li));

      li.append(nameSpan, priceSpan, qtyWrap, deleteBtn);
    }

    list.appendChild(li);
  });

  if (total) total.textContent = _formatPrice(sum);
  _updatePaymentModal(_currentItems, paymentList, paymentTotal);
}

/**
 * 수량 [-][qty][+] 컨트롤을 생성한다.
 * @param {number} itemId
 * @param {number} qty
 * @param {boolean} disabled
 * @returns {HTMLElement}
 */
function _buildQtyControl(itemId, qty, disabled) {
  const wrap = document.createElement("div");
  wrap.className = "qty-control";

  const btnMinus = document.createElement("button");
  btnMinus.className = "btn-qty";
  btnMinus.textContent = "−";
  btnMinus.disabled = disabled || qty <= 1;
  btnMinus.setAttribute("aria-label", "수량 감소");

  const valueSpan = document.createElement("span");
  valueSpan.className = "qty-value";
  valueSpan.textContent = qty;

  const btnPlus = document.createElement("button");
  btnPlus.className = "btn-qty";
  btnPlus.textContent = "+";
  btnPlus.disabled = disabled;
  btnPlus.setAttribute("aria-label", "수량 증가");

  if (!disabled) {
    btnMinus.addEventListener("click", () => {
      const newQty = (parseInt(valueSpan.textContent, 10) || 1) - 1;
      if (newQty < 1) return;
      _emitUpdateQuantity(itemId, newQty);
    });
    btnPlus.addEventListener("click", () => {
      const newQty = (parseInt(valueSpan.textContent, 10) || 1) + 1;
      _emitUpdateQuantity(itemId, newQty);
    });
  }

  wrap.append(btnMinus, valueSpan, btnPlus);
  return wrap;
}

/**
 * [✕] 클릭 시 인라인 삭제 확인 UI로 전환.
 * @param {number} itemId
 * @param {HTMLElement} li
 */
function _onDeleteClick(itemId, li) {
  // 이미 확인 UI가 표시 중이면 무시
  if (li.querySelector(".item-confirm-row")) return;

  // 기존 자식들을 숨긴다
  Array.from(li.children).forEach((el) => { el.style.display = "none"; });

  const confirmRow = document.createElement("div");
  confirmRow.className = "item-confirm-row";

  const msg = document.createElement("span");
  msg.className = "confirm-msg";
  msg.textContent = "정말 삭제할까요?";

  const btnDel = document.createElement("button");
  btnDel.className = "btn-confirm-del";
  btnDel.textContent = "삭제";
  btnDel.addEventListener("click", () => deleteItem(itemId));

  const btnCancel = document.createElement("button");
  btnCancel.className = "btn-confirm-cancel";
  btnCancel.textContent = "취소";
  btnCancel.addEventListener("click", () => updateCart(_currentItems));

  confirmRow.append(msg, btnDel, btnCancel);
  li.appendChild(confirmRow);
}

/**
 * 결제 팝업 내 장바구니 목록 갱신.
 */
function _updatePaymentModal(items, listEl, totalEl) {
  if (!listEl) return;

  if (!items || !items.length) {
    listEl.innerHTML = '<li class="cart-empty">장바구니가 비어있습니다.</li>';
    if (totalEl) totalEl.textContent = "0원";
    return;
  }

  let sum = 0;
  listEl.innerHTML = "";

  items.forEach((item) => {
    const qty = item.quantity || 1;
    sum += (item.price || 0) * qty;

    const li = document.createElement("li");
    li.className = "cart-item";

    const nameSpan = document.createElement("span");
    nameSpan.className = "item-name";
    nameSpan.textContent = qty > 1 ? `${item.name} ×${qty}` : item.name;

    const priceSpan = document.createElement("span");
    priceSpan.className = "item-price";
    priceSpan.textContent = _formatPrice((item.price || 0) * qty);

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
    if (!paidMark) return true;
  }
  return false;
}

/**
 * 항목 삭제 요청.
 * @param {number} itemId
 */
function deleteItem(itemId) {
  if (typeof socket !== "undefined" && socket) {
    socket.emit("delete_item", { item_id: itemId });
  }
}

/**
 * 수량 변경 요청.
 * @param {number} itemId
 * @param {number} newQty
 */
function _emitUpdateQuantity(itemId, newQty) {
  if (newQty < 1) return;
  if (typeof socket !== "undefined" && socket) {
    socket.emit("update_quantity", { item_id: itemId, quantity: newQty });
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
