      <div class="card-section">
        <p class="list-label">Details</p>
        <ul class="detail-list">${detailsList}</ul>
      </div>
      <div class="card-section">
        <p class="list-label">Signals</p>
        <ul class="signal-list">${signals}</ul>
      </div>
      <div class="card-section">
        <p class="list-label">Recommendations</p>
        <ul class="reco-list">${makeList(payload.recommendations || [], "No recommendations")}</ul>
      </div>
      <div class="card-actions">
        ${infoCta}
        ${botsCta}
      </div>
