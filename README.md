# mbta-tracker

Lightweight code for an automatic Massachusetts Bay Transportation Authority (MBTA) train/bus tracker project.
Current functionality is limited; this will expand over time. Some things we will add soon:
- Alerts functionality
- Ferry tracking
- Graphical interface for Raspberry Pi/display header

Sample output (see ```demo.ipynb``` for details):
<table border=\"1\" class=\"dataframe\">
  <thead>
    <tr style=\"text-align: right;\">
      <th></th>
      <th>name</th>
      <th>route</th>
      <th>direction</th>
      <th>toward</th>
      <th>dist</th>
      <th>waits</th>
    </tr>
    <tr>
      <th>id</th>
      <th></th>
      <th></th>
      <th></th>
      <th></th>
      <th></th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>70278</th>
      <td>Assembly</td>
      <td>Orange</td>
      <td>South</td>
      <td>Forest Hills</td>
      <td>0.042979</td>
      <td>[1, 6, 15, 25]</td>
    </tr>
    <tr>
      <th>70279</th>
      <td>Assembly</td>
      <td>Orange</td>
      <td>North</td>
      <td>Oak Grove</td>
      <td>0.045314</td>
      <td>[6, 15, 25]</td>
    </tr>
  </tbody>
</table>
</div>
