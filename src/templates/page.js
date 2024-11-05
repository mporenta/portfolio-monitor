 $(document).ready(function () {
            var dataTable = $('#data_order').DataTable({
                scrollX: true,
                order: [[1, 'desc']],
                ajax: '/orders/data',
                processing: true,
                language: {
                    "processing": '<div class="spinner-border" style="width: 3rem; height: 3rem;" role="status"><span class="visually-hidden">Loading...</span></div><div class="spinner-grow" style="width: 3rem; height: 3rem;" role="status"><span class="visually-hidden">Loading...</span></div>'
                },
                columns: [
                    {
                        data: null,
                        render: function (data, type, row) {
                            if (type === 'display') {
                                if (row.unrealizedpnl != 0) {
                                    return '<button class="btn btn-warning close-position" data-ticker="' + row.ticker + '" data-position="' + row.position + '">Close Position</button>';
                                } else if ((row.position == 0 && row.orderstatus != "Portfolio") && (row.orderstatus === "PreSubmitted" || row.orderstatus === "Submitted")) {
                                    return '<button class="btn cancel-order" data-ticker="' + row.ticker + '" style="background-color: #f74f4f; color: black;">Cancel Order</button>';
                                }
                            }
                            return '';
                        }
                    },
                    {
                        data: 'uniquekey',
                        render: function (data, type) {
                            if (type === 'display') {
                                return moment.utc(data).tz("America/New_York").format('YYYY-MM-DD HH:mm:ss.SSS');
                            }
                            return data;
                        }
                    },
                    {
                        data: 'timestamp',
                        render: function (data, type) {
                            if (type === 'display') {
                                return moment.utc(data).tz("America/New_York").format('YYYY-MM-DD HH:mm:ss.SSS');
                            }
                            return data;
                        }
                    },
                    { data: 'ticker' },
                    { data: 'tv_price' },
                    {
                        data: 'action',
                        render: function (data, type) {
                            if (type === 'display') {
                                let color = 'orange';
                                switch (data) {
                                    case 'SELL': color = 'red'; break;
                                    case 'BUY': color = 'green'; break;
                                }
                                return '<span style="color:' + color + '">' + data + '</span>';
                            }
                            return data;
                        },
                    },
                    { data: 'ordertype' },
                    { data: 'qty' },
                    { data: 'lmtprice' },
                    { data: 'auxprice' },
                    { data: 'orderid' },
                    { data: 'orderref' },
                    { data: 'orderstatus' },
                    {
                        data: 'position',
                        render: function (data, type) {
                            if (type === 'display') {
                                let color = data >= 0 ? 'black' : 'red';
                                return '<span style="color:' + color + '">' + data + '</span>';
                            }
                            return data;
                        },
                    },
                    { data: 'mrkvalue' },
                    {
                        data: 'avgfillprice',
                        render: function (data, type) {
                            var number = $.fn.dataTable.render.number('', '.', 2, '').display(data);
                            if (type === 'display') {
                                let color = number >= 0 ? 'black' : 'green';
                                return '<span style="color:' + color + '">' + number + '</span>';
                            }
                            return number;
                        },
                    },
                    {
                        data: 'unrealizedpnl',
                        render: function (data, type) {
                            var number = $.fn.dataTable.render.number('', '.', 2, '').display(data);
                            if (type === 'display' || type === 'filter') {
                                let color = number >= 0 ? 'black' : 'red';
                                if (parseFloat(number) === Number.MAX_VALUE) number = 0;
                                return '<span style="color:' + color + '">' + number + '</span>';
                            }
                            return number;
                        },
                    },
                    {
                        data: 'realizedpnl',
                        render: function (data, type) {
                            var number = $.fn.dataTable.render.number('', '.', 2, '').display(data);
                            if (type === 'display') {
                                let color = number >= 0 ? 'black' : 'red';
                                return '<span style="color:' + color + '">' + number + '</span>';
                            }
                            return number;
                        },
                    },
                ]
            });
            // Add this inside your document.ready function
            var activePositionsTable = $('#active-positions').DataTable({
                responsive: true,
                paging: false,
                searching: false,
                info: false
            });

            var closedPositionsTable = $('#closed-positions').DataTable({
                responsive: true,
                paging: false,
                searching: false,
                info: false
            });
           dataTable.on('xhr', function (e, settings, json) {
    var data = dataTable.data();
    
    // 1. Handle Status Filters
    var statuses = new Set();
    data.each(function (row) {
        if (row.orderstatus) {
            statuses.add(row.orderstatus);
        }
    });

    // Update status filter dropdown
    var statusFilter = $('#statusFilter');
    statusFilter.empty();
    statusFilter.append('<option value="">All Statuses</option>');
    Array.from(statuses).sort().forEach(function (status) {
        statusFilter.append(`<option value="${status}">${status}</option>`);
    });
    
    // Maintain selected value
    var selectedValue = statusFilter.val();
    if (selectedValue) {
        statusFilter.val(selectedValue);
    }

    // 2. Calculate Summary Panel Values
    var totals = Array.from(data).reduce((acc, row) => {
        acc.unrealizedPnL += parseFloat(row.unrealizedpnl) || 0;
        acc.realizedPnL += parseFloat(row.realizedpnl) || 0;
        return acc;
    }, {
        unrealizedPnL: 0,
        realizedPnL: 0
    });

    const dailyPnL = totals.unrealizedPnL + totals.realizedPnL;
    const riskFactor = parseFloat($('#riskFactor').val()) || 0.01;
    const netLiquidation = parseFloat(json.net_liquidation) || 0;
    const riskAmount = netLiquidation * riskFactor;

    // 3. Update Summary Panel
    $('#daily-pnl').text(`$${dailyPnL.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
    $('#unrealized-pnl').text(`$${totals.unrealizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
    $('#realized-pnl').text(`$${totals.realizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
    $('#net-liquidation').text(`$${netLiquidation.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
    $('#risk-amount').text(`$${riskAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

    // 4. Update Position Tables
    updatePositionTables(data);
});

            // Add risk factor change handler
            $('#riskFactor').on('change', function () {
                const riskFactor = parseFloat($(this).val()) || 0.01;
                const netLiquidation = parseFloat($('#net-liquidation').text().replace('$', '').replace(',', '')) || 0;
                const riskAmount = netLiquidation * riskFactor;
                $('#risk-amount').text(`$${riskAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
            });

            // Function to update position tables
            function updatePositionTables(data) {
                // Clear existing data
                activePositionsTable.clear();
                closedPositionsTable.clear();

                // Separate active and closed positions
                Array.from(data).forEach(row => {
                    if (row.position !== 0) {
                        activePositionsTable.row.add([
                            row.ticker,
                            row.position,
                            row.tv_price,
                            row.mrkvalue,
                            row.avgfillprice,
                            row.unrealizedpnl,
                            row.action  // Using action as exchange
                        ]);
                    } else if (row.realizedpnl !== 0) {
                        closedPositionsTable.row.add([
                            row.ticker,
                            row.qty,
                            row.tv_price,
                            row.realizedpnl,
                            row.action  // Using action as exchange
                        ]);
                    }
                });

                // Redraw tables
                activePositionsTable.draw();
                closedPositionsTable.draw();
            }
                  // Update status filter dropdown
            var statusFilter = $('#statusFilter');
            statusFilter.empty();
            statusFilter.append('<option value="">All Statuses</option>');

            Array.from(statuses).sort().forEach(function (status) {
                statusFilter.append(`<option value="${status}">${status}</option>`);
            });

            // Maintain selected value if exists
            var selectedValue = statusFilter.val();
            if (selectedValue) {
                statusFilter.val(selectedValue);
            }
            // Function to update status filter
            function updateStatusFilter() {
                var statusColumn = dataTable.column(12); // orderstatus column
                var statusData = statusColumn.data().unique();

                var statusFilter = $('#statusFilter');
                statusFilter.empty();
                statusFilter.append('<option value="">All Statuses</option>');

                statusData.sort().each(function (status) {
                    if (status) { // only add non-empty statuses
                        statusFilter.append(`<option value="${status}">${status}</option>`);
                    }
                });
            }

           

        

            // Handle status filter change
            $('#statusFilter').on('change', function () {
                var selectedStatus = $(this).val();
                dataTable.column(12)  // orderstatus column
                    .search(selectedStatus ? '^' + selectedStatus + '$' : '', true, false)
                    .draw();
            });



            $('#data_order').on('click', '.close-position, .cancel-order', function () {
                const ticker = $(this).data('ticker');
                const isClosePosition = $(this).hasClass('close-position');
                const ngrokUrl = $('#ngrokUrl').val() || 'https://tv.porenta.us//webhook';
                const tokenKey = $('#tokenKey').val() || 'WebhookReceived:fcbd3d';
                const timestamp = Date.now();

                const payload = {
                    timestamp: timestamp,
                    ticker: ticker,
                    currency: "USD",
                    timeframe: "S",
                    clientId: 1,
                    key: tokenKey,
                    contract: "stock",
                    orderRef: isClosePosition ? "cancel_all_test" : "cancel_all",
                    direction: isClosePosition ? "strategy.close_all" : "strategy.cancel_all",
                    metrics: [
                        { "name": "entry.limit", "value": 0 },
                        { "name": "entry.stop", "value": 0 },
                        { "name": "exit.limit", "value": 0 },
                        { "name": "exit.stop", "value": 0 },
                        { "name": "qty", "value": -10000000000 },
                        { "name": "price", "value": 4.275 }
                    ]
                };

                $.ajax({
                    url: ngrokUrl,
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify(payload),
                    success: function (response) {
                        $('#responseMessage').html('<div class="alert alert-success">' + (isClosePosition ? 'Position close' : 'Order cancellation') + ' request sent successfully. Refreshing data...</div>');
                        refreshDataTable();
                    },
                    error: function (jqXHR, textStatus, errorThrown) {
                        let responseHtml = '<div class="alert alert-danger">';
                        responseHtml += '<h4>Failed to send ' + (isClosePosition ? 'position close' : 'order cancellation') + ' request</h4>';
                        responseHtml += '<p><strong>Status:</strong> ' + textStatus + '</p>';
                        responseHtml += '<p><strong>Error:</strong> ' + errorThrown + '</p>';
                        if (jqXHR.responseText) {
                            responseHtml += '<p><strong>Response:</strong></p>';
                            responseHtml += '<pre>' + jqXHR.responseText + '</pre>';
                        }
                        responseHtml += '</div>';
                        $('#responseMessage').html(responseHtml);
                    }
                });
            });

            function refreshDataTable() {
                dataTable.ajax.reload(function (json) {
                    $('#responseMessage').html('<div class="alert alert-info">Data refreshed. Showing latest positions.</div>');
                    console.log('DataTable has been refreshed. New data:', json);
                }, false);
            }
        });