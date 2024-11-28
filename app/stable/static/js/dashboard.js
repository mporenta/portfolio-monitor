async function fetchData() {
  try {
    // Fetch Current P&L
    const pnlResponse = await fetch("/api/current-pnl");
    const pnlData = await pnlResponse.json();
    updatePnLMetrics(pnlData.data);

    // Fetch Trades
    const tradesResponse = await fetch("/api/trades");
    const tradesData = await tradesResponse.json();
    updateTrades(tradesData.data.trades);

    // Fetch Active Positions
    const positionsResponse = await fetch("/api/positions");
    const positionsData = await positionsResponse.json();
    updatePositions(positionsData.data.active_positions);
  } catch (error) {
    console.error("Error fetching data:", error);
  }
}
async function fetchAlerts() {
  try {
    const currentTime = new Date().getTime();
    const response = await fetch(
      `https://tv.porenta.us/alerts/data?_=${currentTime}`
    );
    const result = await response.json();
    updateAlerts(result.data);
  } catch (error) {
    console.error("Error fetching alerts:", error);
  }
}



  function updateAlerts(alerts) {
    const alertsTable = document.getElementById('alerts');
    if (!alerts || alerts.length === 0) {
      alertsTable.innerHTML = '<tr><td colspan="8" class="text-center p-4">No alerts found.</td></tr>';
      return;
    }

    alertsTable.innerHTML = alerts.map(alert => `
        <tr class="bg-gray-800 hover:bg-gray-700">
            <td class="border border-gray-700 px-4 py-2">${alert.alertstatus}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.direction}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.entrylimit.toFixed(2)}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.entrystop.toFixed(2)}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.exitlimit.toFixed(2)}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.exitstop.toFixed(2)}</td>
            <td class="border border-gray-700 px-4 py-2">${alert.ticker}</td>
            <td class="border border-gray-700 px-4 py-2">${toDenverTime(alert.timestamp, 'long')}</td>
        </tr>
    `).join('');
  }
  // Convert a timestamp to the America/Denver time zone
  function toDenverTime(timestamp, format = "short") {
    const options = {
      timeZone: "America/Denver",
      hour12: true, // Set to false for 24-hour format
    };

    if (format === "short") {
      Object.assign(options, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        fractionalSecondDigits: 3,
      });
    } else if (format === "long") {
      Object.assign(options, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        fractionalSecondDigits: 3,
      });
    }

    return new Intl.DateTimeFormat("en-US", options).format(new Date(timestamp));
    // Example usage:
    console.log(toDenverTime("2024-11-25T14:16:16.509Z", "long"));
    console.log(toDenverTime("2024-11-25T14:16:16.509Z", "short"));
    ;
  }

  function updatePnLMetrics(data) {
    const pnlMetrics = document.getElementById("pnl-metrics");
    pnlMetrics.innerHTML = `
                <div class="bg-gray-700 p-4 rounded shadow text-center">
                    <p class="text-gray-300">Daily P&L</p>
                    <p class="text-xl ${data.daily_pnl >= 0 ? "text-green-500" : "text-red-500"
      }">${data.daily_pnl.toFixed(2)}</p>
                </div>
                <div class="bg-gray-700 p-4 rounded shadow text-center">
                    <p class="text-gray-300">Total Unrealized P&L</p>
                    <p class="text-xl ${data.total_unrealized_pnl >= 0
        ? "text-green-500"
        : "text-red-500"
      }">${data.total_unrealized_pnl.toFixed(2)}</p>
                </div>
                <div class="bg-gray-700 p-4 rounded shadow text-center">
                    <p class="text-gray-300">Total Realized P&L</p>
                    <p class="text-xl ${data.total_realized_pnl >= 0
        ? "text-green-500"
        : "text-red-500"
      }">${data.total_realized_pnl.toFixed(2)}</p>
                </div>
                <div class="bg-gray-700 p-4 rounded shadow text-center">
                    <p class="text-gray-300">Net Liquidation</p>
                    <p class="text-xl text-blue-500">${data.net_liquidation.toFixed(
        2
      )}</p>
                </div>
            `;
  }

  function updateTrades(trades) {
    const tradesTable = document.getElementById("trades");
    tradesTable.innerHTML = trades
      .map(
        (trade) => `
                <tr class="bg-gray-800 hover:bg-gray-700">
                    <td class="border border-gray-700 px-4 py-2">${toDenverTime(alert.timestamp, 'long')}</td>
                    <td class="border border-gray-700 px-4 py-2">${trade.symbol
          }</td>
                    <td class="border border-gray-700 px-4 py-2">${trade.action
          }</td>
                    <td class="border border-gray-700 px-4 py-2">${trade.quantity
          }</td>
                    <td class="border border-gray-700 px-4 py-2">${trade.fill_price.toFixed(
            2
          )}</td>
                    <td class="border border-gray-700 px-4 py-2">${trade.commission.toFixed(
            2
          )}</td>
                    <td class="border border-gray-700 px-4 py-2 ${trade.realized_pnl >= 0
            ? "text-green-500"
            : "text-red-500"
          }">${trade.realized_pnl.toFixed(2)}</td>
                </tr>
            `
      )
      .join("");
  }

  function updatePositions(positions) {
    const positionsTable = document.getElementById("positions");
    positionsTable.innerHTML = positions
      .map(
        (position) => `
                <tr class="bg-gray-800 hover:bg-gray-700">
                    <td class="border border-gray-700 px-4 py-2">${position.symbol
          }</td>
                    <td class="border border-gray-700 px-4 py-2">${position.position
          }</td>
                    <td class="border border-gray-700 px-4 py-2">${position.market_price.toFixed(
            2
          )}</td>
                    <td class="border border-gray-700 px-4 py-2">${position.market_value.toFixed(
            2
          )}</td>
                    <td class="border border-gray-700 px-4 py-2">${position.average_cost.toFixed(
            2
          )}</td>
                    <td class="border border-gray-700 px-4 py-2 ${position.unrealized_pnl >= 0
            ? "text-green-500"
            : "text-red-500"
          }">${position.unrealized_pnl.toFixed(2)}</td>
                </tr>
            `
      )
      .join("");
  }




}
// Fetch data on page load
document.addEventListener("DOMContentLoaded", fetchData);