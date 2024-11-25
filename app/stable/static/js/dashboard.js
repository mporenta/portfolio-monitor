// Format timestamps in Denver timezone
document.addEventListener('DOMContentLoaded', () => {
  // Override the default rendering for these columns in any DataTable
  $.fn.dataTable.render.denverTime = function () {
    return function (data, type, row) {
      if (type === 'display') {
        return moment(data).tz('America/Denver').format('HH:mm:ss.SSS');
      }
      return data;
    };
  };

  // Override the default rendering for full datetime format
  $.fn.dataTable.render.denverDateTime = function () {
    return function (data, type, row) {
      if (type === 'display') {
        return moment(data).tz('America/Denver').format('MM-DD-YYYY hh:mm:ss.SSS A');
      }
      return data;
    };
  };

  // Find existing DataTables and update their column renderers
  const tables = $.fn.dataTable.tables({ api: true });
  tables.each(function () {
    const table = $(this).DataTable();
    const tableId = $(this).attr('id');

    // Get column indexes
    table.columns().every(function () {
      const columnData = this.dataSrc();

      if (['trade_time', 'tv_timestamp', 'uniquekey'].includes(columnData)) {
        const renderer = tableId === 'past-trades-table' ?
          $.fn.dataTable.render.denverDateTime() :
          $.fn.dataTable.render.denverTime();

        this.render(renderer);
      }
    });

    // Redraw table with new renderers
    table.draw();
  });
});



    document.addEventListener('DOMContentLoaded', () => {
      const activePositionsTable = new DataTable('#active-positions', {
        responsive: true,
    order: [[6, 'desc']],
    deferRender: true,
    processing: true,
    columns: [
    {
        data: null,
    render: function (data, type, row) {
              if (type === 'display') {
                return `<button class="close-position-btn" data-symbol="${row.symbol}">Close Position</button>`;
              }
    return '';
            }
          },
    {data: 'symbol' },
    {data: 'position' },
    {
        data: 'market_price',
            render: (data) => `$${data.toFixed(2)}`
          },
    {
        data: 'market_value',
            render: (data) => `$${data.toFixed(2)}`
          },
    {
        data: 'average_cost',
            render: (data) => `$${data.toFixed(2)}`
          },
    {
        data: 'unrealized_pnl',
            render: (data) => {
              const color = data >= 0 ? 'positive' : 'negative';
    return `<span class="${color}">$${data.toFixed(2)}</span>`;
            }
          },
    {data: 'exchange' }
    ]
      });
    // Initialize alerts table
    const alertsTable = new DataTable('#alerts-table', {
        responsive: true,
    order: [[0, 'desc']], // Sort by time descending
    deferRender: true,
    processing: true,

    columns: [
    {
        data: 'tv_timestamp',
            render: (data) => {
              const date = moment.tz(data, 'YYYY-MM-DD HH:mm:ss.SSS', 'UTC').tz('America/Denver');
    return `<span class="trade-time">${date.format('MM-DD-YYYY h:mm:ss.SSS A')}</span>`;
            }
          },
    {
        data: 'uniquekey',
            render: (data) => {
              const date = moment.tz(data, 'YYYY-MM-DD HH:mm:ss.SSS', 'UTC').tz('America/Denver');
    return `<span class="trade-time">${date.format('MM-DD-YYYY h:mm:ss.SSS A')}</span>`;
            }
          },


    {
        data: 'alertstatus',
            render: (data) => `<span class="position-status ${data === 'SUBMITTED' ? 'position-active' : ''}">${data}</span>`
          },
    {
        data: 'direction',
            render: (data) => {
              const isEntry = data.includes('entry');
    const isBuy = data.includes('long');
    const color = isEntry ? (isBuy ? 'positive' : 'negative') : '';
    return `<span class="${color}">${data}</span>`;
            }
          },
    {data: 'ticker' },
    {data: 'orderref' },
   
  
    
    {
        data: 'tv_price',
            render: (data) => `$${parseFloat(data).toFixed(2)}`
          }
    ],
    createdRow: function (row, data, dataIndex) {
          if (data.direction.includes('close_all') || data.direction.includes('cancel_all')) {
        $(row).addClass('trade-sell');
          } else if (data.direction.includes('entrylong')) {
        $(row).addClass('trade-buy');
          }
        }
      });

    const tradesTable = new DataTable('#trades-table', {
        responsive: true,
    order: [[0, 'desc']], // Sort by time descending
    deferRender: true,
    processing: true,
    columns: [
    {
        data: 'trade_time',
            render: (data) => {
              const date = new Date(data);
    return `<span class="trade-time">${date.toLocaleTimeString()}</span>`;
            }
          },
    {data: 'symbol' },
    {
        data: 'action',
            render: (data) => `<span class="${data === 'BUY' ? 'positive' : 'negative'}">${data}</span>`
          },
    {data: 'quantity' },
    {
        data: 'fill_price',
            render: (data) => `$${parseFloat(data).toFixed(2)}`
          },
    {
        data: 'commission',
            render: (data) => data ? `$${parseFloat(data).toFixed(2)}` : '-'
          },
    {
        data: 'realized_pnl',
            render: (data) => {
              if (!data) return '-';
    const value = parseFloat(data);
              const color = value >= 0 ? 'positive' : 'negative';
    return `<span class="${color}">$${value.toFixed(2)}</span>`;
            }
          },
    {data: 'exchange' },
    {data: 'order_ref' },
    {
        data: 'status',
            render: (data) => `<span class="position-status ${data === 'Filled' ? 'position-active' : ''}">${data}</span>`
          }
    ],
    createdRow: function (row, data, dataIndex) {
        $(row).addClass(`trade-${data.action.toLowerCase()}`);
        }
      });
    const pastTradesTable = new DataTable('#past-trades-table', {
        responsive: true,
    order: [[0, 'desc']], // Sort by time descending
    deferRender: true,
    processing: true,
    columns: [
    {
        data: 'trade_time',
            render: (data) => {
              const date = new Date(data);
    return `<span class="trade-time">${date.toLocaleString()}</span>`; // Show full date and time for past trades
            }
          },
    {data: 'symbol' },
    {
        data: 'action',
            render: (data) => `<span class="${data === 'BUY' ? 'positive' : 'negative'}">${data}</span>`
          },
    {data: 'quantity' },
    {
        data: 'fill_price',
            render: (data) => `$${parseFloat(data).toFixed(2)}`
          },
    {
        data: 'commission',
            render: (data) => data ? `$${parseFloat(data).toFixed(2)}` : '-'
          },
    {
        data: 'realized_pnl',
            render: (data) => {
              if (!data) return '-';
    const value = parseFloat(data);
              const color = value >= 0 ? 'positive' : 'negative';
    return `<span class="${color}">$${value.toFixed(2)}</span>`;
            }
          },
    {data: 'exchange' },
    {data: 'order_ref' },
    {
        data: 'status',
            render: (data) => `<span class="position-status ${data === 'Filled' ? 'position-active' : ''}">${data}</span>`
          }
    ],
    createdRow: function (row, data, dataIndex) {
        $(row).addClass(`trade-${data.action.toLowerCase()}`);
        }
      });


    // Add click handler for close position buttons
    $('#active-positions').on('click', '.close-position-btn', async function () {
        const button = $(this);

    try {
        button.prop('disabled', true)
            .addClass('loading')
            .text('Closing...');

    // Get data for the row where the button was clicked
    const rowData = activePositionsTable.row($(this).closest('tr')).data();

    // Determine action and quantity based on position
    const quantity = Math.abs(rowData.position);
          const action = rowData.position > 0 ? 'SELL' : 'BUY';
    const marketPrice = rowData.market_price;

    const positionToClose = {
        symbol: rowData.symbol,
    action: action,
    quantity: quantity,
    price: marketPrice

          };

    // Call both endpoints asynchronously
    await Promise.all([
    // Original webhook call
    fetch("/proxy/webhook", {
        method: "POST",
    headers: {"Content-Type": "application/json" },
    body: JSON.stringify({
        timestamp: Date.now(),
    ticker: rowData.symbol,
    currency: "USD",
    timeframe: "S",
    clientId: 1,
    key: "mrsprinkles",
    contract: "stock",
    orderRef: "close_all",
    direction: "strategy.close_all",
    metrics: [
    {name: "entry.limit", value: 0 },
    {name: "entry.stop", value: 0 },
    {name: "exit.limit", value: 0 },
    {name: "exit.stop", value: 0 },
    {name: "qty", value: -10000000000 },
    {name: "price", value: 5.00 }
    ]
              })
            }),

    // New close_positions endpoint call
    fetch("/close_positions", {
        method: "POST",
    headers: {"Content-Type": "application/json" },
    body: JSON.stringify({
        positions: [positionToClose]
              })
            })
    ]);


    button.removeClass('loading')
    .addClass('success')
    .text('Closed');

          setTimeout(() => {
        refreshData();
          }, 2000);

        } catch (error) {
        console.error("Error closing position:", error);
    button.removeClass('loading')
    .addClass('error')
    .text('Failed');

          setTimeout(() => {
        button.removeClass('error')
            .prop('disabled', false)
            .text('Close Position');
          }, 3000);
        }
      });

    async function updateAlerts() {
        try {
          const currentTime = new Date().getTime();
    const response = await fetch(`https://tv.porenta.us/alerts/data?_=${currentTime}`);
    const result = await response.json();

    if (result.data) {
            const today = moment().tz('America/Denver').startOf('day');

            const filteredData = result.data.filter(alert => {
              const date = moment.tz(alert.tv_timestamp, 'YYYY-MM-DD HH:mm:ss.SSS', 'UTC').tz('America/Denver');
    return date.isSame(today, 'day');
            });

    alertsTable.clear();
    alertsTable.rows.add(filteredData).draw();
          }
        } catch (error) {
        console.error('Error fetching alerts data:', error);
        }
      }


    async function updatePositions() {
        try {
          const response = await fetch('/api/positions');
    const result = await response.json();
    if (result.status === 'success' && result.data.active_positions) {
            // Format data before adding to table
            const formattedPositions = result.data.active_positions.map(pos => ({
        ...pos,
        market_price: pos.market_price || 0,
    market_value: pos.market_value || 0,
    average_cost: pos.average_cost || 0,
    unrealized_pnl: pos.unrealized_pnl || 0,
    position: pos.position || 0
            }));
    activePositionsTable.clear();
    activePositionsTable.rows.add(formattedPositions).draw();
          } else {
        console.error('Error fetching positions data:', result.message);
          }
        } catch (error) {
        console.error('Error fetching positions data:', error);
        }
      }

    async function updatePnlData() {
        try {
          const response = await fetch('/api/current-pnl');
    const result = await response.json();
    if (result.status === 'success') {
            const pnlData = result.data;

            // Format function to handle null values and add commas
            const formatValue = (value) => {
              if (value === null || value === undefined) return '$0.00';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
    currency: 'USD'
              }).format(value);
            };

    document.getElementById('daily-pnl').textContent = formatValue(pnlData.daily_pnl);
    document.getElementById('unrealized-pnl').textContent = formatValue(pnlData.total_unrealized_pnl);
    document.getElementById('realized-pnl').textContent = formatValue(pnlData.total_realized_pnl);
    document.getElementById('net-liquidation').textContent = formatValue(pnlData.net_liquidation);
          } else {
        console.error('Error fetching current PnL data:', result.message);
          }
        } catch (error) {
        console.error('Error fetching current PnL data:', error);
        }
      }

    async function updateTrades() {
        try {
          const response = await fetch('/api/trades');
    const result = await response.json();
    if (result.status === 'success') {
            const today = new Date();
    today.setHours(0, 0, 0, 0);

            // Format trades data to handle null values
            const formatTrade = trade => ({
        ...trade,
        fill_price: trade.fill_price || 0,
    commission: trade.commission || null,
    realized_pnl: trade.realized_pnl || null,
    quantity: trade.quantity || 0,
    trade_time: trade.trade_time || new Date().toISOString()
            });

    // Split trades into today and past
    const trades = result.data.trades.map(formatTrade);
    const todayTrades = [];
    const pastTrades = [];

            trades.forEach(trade => {
              const tradeDate = new Date(trade.trade_time);
    tradeDate.setHours(0, 0, 0, 0);

    if (tradeDate.getTime() === today.getTime()) {
        todayTrades.push(trade);
              } else {
        pastTrades.push(trade);
              }
            });

    // Update today's trades table
    tradesTable.clear();
    tradesTable.rows.add(todayTrades).draw();

    // Update past trades table
    pastTradesTable.clear();
    pastTradesTable.rows.add(pastTrades).draw();

          } else {
        console.error('Error fetching trades data:', result.message);
          }
        } catch (error) {
        console.error('Error fetching trades data:', error);
        }
      }
    // Make refreshData available globally
    window.refreshData = function () {
        updatePositions();
    updatePnlData();
    updateTrades();
    updateAlerts();
      };

    // Initial data load
    refreshData();

    // Refresh data every 5 minutes (300000 ms)
    setInterval(refreshData, 300000);
    });




